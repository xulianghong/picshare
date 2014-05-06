import os
import requests
import sqlite3
import time
import hashlib
from flask import Flask, request, redirect, url_for, flash, render_template, session, g, abort, send_from_directory
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = '/tmp/pics'
#ALLOWED_EXTENSIONS = set(['txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'])

tmpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=tmpl_dir)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config.from_object(__name__)

# Load default config and override config from an environment variable
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'picshare.db'),
    DEBUG=True,
    SECRET_KEY='development key',
    CREDENTIALS={'user1':'pass1', 'user2':'pass2', 'user3':'pass3'},
    TIMEOUT=1000000,
    TPC_TIMEOUT = 1000000,
))
app.config.from_envvar('PICSHARE_SETTINGS', silent=True)

def connect_db():
    """Connects to the specific database."""
    rv = sqlite3.connect(app.config['DATABASE'])
    #rv.row_factory = sqlite3.Row
    return rv

def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = connect_db()
    return g.sqlite_db

def get_peers():
    db = get_db()
    cur = db.execute('select name from servers where id>1')
    res = cur.fetchall()
    if res != None:
        return [record[0] for record in res]
    else:
        return None

def get_myurl():
    db = get_db()
    cur = db.execute('select name from servers where id=1')
    # should never be None
    return cur.fetchone()[0]

@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()


def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

@app.route('/')
def start():
    return render_template('login.html')

@app.route('/upload/<event_id>', methods=['GET', 'POST'])
def upload_file(event_id):
    if request.method == 'POST':
        file = request.files['file']
        if file:
            filename = secure_filename(file.filename)
            save_file(event_id, file, filename)

            while tpc_prepare() == 'abort':
                tpc_abort()
            args = {'method' : 'save_file', 
                'event_id' : str(event_id), 'filename' : filename}
            tpc_commit(**args)
            flash("Image uploaded successfully!")
    return redirect(url_for('publish_pics')) 

def save_file(event_id, file, filename):
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], str(event_id), filename))
        

def get_current_event_id():
    db = get_db()
    cur = db.execute('''select event_id from events where status="pending" or status="created"''')
    res = cur.fetchone()
    if res != None:
        # previous event in progress
        event_id = res[0] 
    else: 
        cur = db.execute('''select max(event_id) from events where \
            status= "success" or status = "abort"''')
        res = cur.fetchone()
        if res != None:
            event_id = res[0]
        else:
            event_id = None
    return event_id

def create_new_event(event_name):
    db = get_db()
    epoch_time = int(time.time())
    db.execute('''insert or ignore into events (name, status, timestamp) values (?, ?, ?)''',
        [event_name, "created", epoch_time])
    db.commit()

    cur = db.execute('select max(event_id) from events')
    res = cur.fetchone()
    if res != None:
        event_id = res[0]
    else:
        event_id = None
    create_event_dir(event_id)
    return event_id

def create_event_dir(event_id):
    if event_id == None:
        return
    event_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(event_id))
    if not os.path.exists(event_dir):
        os.makedirs(event_dir)

def get_agree(event_id, username):
    if event_id == None:
        return None

    db = get_db()
    cur = db.execute('select agree from entries where event_id=? and username=?', 
        [event_id, username])
    res = cur.fetchone()
    if res != None:
        agree = res[0]
    else:
        agree = None
    return agree

def get_event_dir(eid):
    event_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(eid))
    return event_dir

def get_event_id_by_name(ename):
    db = get_db()
    cur = db.execute('select event_id from events where \
        name=? and status=?', [ename, "success"])
    res = cur.fetchone()
    if res != None:
        return res[0]
    else:
        return None

def get_status(event_id):
    if event_id == None:
        return None

    db = get_db()
    cur = db.execute('select status from events where event_id=(?)', (event_id,))
    res = cur.fetchone()
    if res != None:
        status = res[0]
    else:
        status = None
    return status

def pub_event(event_id):
    pub_time = int(time.time())
    db = get_db()
    db.execute('update events set status="pending", timestamp=? where event_id=?', [pub_time, event_id]) 
    db.commit()

def try_commit_event(event_id):
    db = get_db()
    cur = db.execute('select count(*) as count from entries where agree=1 and event_id=?', (event_id,))
    num_agrees = int(cur.fetchone()[0])
    if num_agrees == len(app.config['CREDENTIALS']):
        db.execute('update events set status=? where event_id=?', ['success', event_id])
        db.commit()

def abort_event(event_id):
    db = get_db()
    db.execute('update events set status=? where event_id=?', ['abort', event_id])
    db.commit()


def event_timeout(event_id):
    if event_id == None:
        return None
    db = get_db()
    cur = db.execute('select timestamp from events where event_id=?', (event_id,))
    res = cur.fetchone()
    timestamp = res[0]
    cur_time = int(time.time())
    if cur_time - timestamp > app.config['TIMEOUT']:
        return 1
    else:
        return 0

def vote(event_id, username, agree):
    db = get_db()
    db.execute('insert into entries (event_id, username, agree) values (?, ?, ?)',
        [event_id, username, agree])
    db.commit()

@app.route('/publish/', methods=['GET', 'POST'])
def publish_pics():
    eid = get_current_event_id()
    timeout = event_timeout(eid)
    status = get_status(eid)
    sfiles = None
    s_eid = None

    if timeout == 1:
        while tpc_prepare() == 'abort':
            tpc_abort()
        args = {'method' : 'abort_event', 'event_id' : str(eid)}
        tpc_commit(**args)
        abort_event(eid)
        flash('Event aborted due to timeout')
        
    elif request.method == 'POST':
        if request.form.get('create', None) == 'Create':
            event_name = request.form.get('eventname', None)
            if eid == None or status == "abort" or status == "success":
                while tpc_prepare() == 'abort':
                    tpc_abort()
                args = {'method' : 'create_new_event', 'event_name' : event_name}
                tpc_commit(**args)
                eid = create_new_event(event_name)
            else:
                flash('Previous event not finished yet! Cannot create!')

        elif request.form.get('search', None) == 'Search':
            event_name = request.form.get('ename', None)
            s_eid = get_event_id_by_name(event_name) 
            if s_eid == None:
                sfiles = None
            else:
                s_event_dir = get_event_dir(s_eid)
                if os.path.exists(s_event_dir):
                    sfiles = os.listdir(s_event_dir)
                    if len(sfiles) == 0:
                        sfiles = None
                          

        elif request.form.get('pub', None) == 'Publish':
            files = None
            if eid != None:
                event_dir = get_event_dir(eid)
                files = os.listdir(event_dir)
            if len(files) == 0:
                flash('Cannot publish: empty event!')
            elif status != 'created':
                flash('Cannot publish: publishing in progress or done!')   
            elif status == "created" and len(files) > 0:
                # publish event
                while tpc_prepare() == 'abort':
                    tpc_abort()
                args = {'method' : 'pub_event', 'event_id' : str(eid)}
                tpc_commit(**args)
                pub_event(eid)

        elif request.form.get('upload', None) == 'Upload':
            file = request.files['file']
            if file:
                filename = secure_filename(file.filename)
                save_file(eid, file, filename)

                while tpc_prepare() == 'abort':
                    tpc_abort()
                args = {'method' : 'save_file', 
                    'event_id' : str(eid), 'filename' : filename}
                tpc_commit(**args)
                flash("Image uploaded successfully!")

        elif request.form.get('vote', None) == 'Yes':
            # vote yes
            while tpc_prepare() == 'abort':
                tpc_abort()
            args = {'method' : 'vote', 'event_id' : str(eid), 'username': session['username'], 'agree' : 1}
            tpc_commit(**args)
            vote(eid, session['username'], 1)

            # try commit
            while tpc_prepare() == 'abort':
                tpc_abort()
            args = {'method' : 'try_commit_event', 'event_id' : str(eid)}
            tpc_commit(**args)
            try_commit_event(eid)

        elif request.form.get('vote', None) == 'No':
            # vote no 
            while tpc_prepare() == 'abort':
                tpc_abort()
            args = {'method' : 'vote', 'event_id' : str(eid), 'username': session['username'], 'agree' : 0}
            tpc_commit(**args)
            vote(eid, session['username'], 0)

            # abort event
            while tpc_prepare() == 'abort':
                tpc_abort()
            args = {'method' : 'abort_event', 'event_id' : str(eid)}
            tpc_commit(**args)
            abort_event(eid)

    eid = get_current_event_id()
    agree = get_agree(eid, session['username'])
    status = get_status(eid)
    
    
    files = None
    if eid != None:
        event_dir = get_event_dir(eid)
        if os.path.exists(event_dir):
            files = os.listdir(event_dir)
            if len(files) == 0:
                files = None
    return render_template('show_pics.html', event_id=eid, files=files, s_eid=s_eid, sfiles=sfiles, agree=agree, status=status)


@app.route('/uploads/<event_id>/<filename>')
def uploaded_file(event_id, filename):
    event_dir = get_event_dir(event_id)
    return send_from_directory(event_dir, filename)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = request.form['username']
        if user not in app.config['CREDENTIALS'].keys():
            error = 'Invalid username'
        elif request.form['password'] != app.config['CREDENTIALS'][user]:
            error = 'Invalid password'
        else:
            session['logged_in'] = True
            session['username'] = user
            flash('You were logged in')
            return redirect(url_for('publish_pics'))
    return render_template('login.html', error=error)


@app.route('/vote/<ack>')
def vote_test(ack):
    return render_template('login.html')

def add_trans(id, type, server, commit_args=None):
    db = get_db()
    timestamp = int(time.time())
    db.execute('insert or ignore into transactions \
        (tid, type, timestamp, server, commit_args) \
        values (?, ?, ?, ?, ?)', [id, type, timestamp, server, commit_args])
    db.commit()

def new_tid():
    cur_tid = get_cur_tid()
    return cur_tid + 1

def get_lock():
    db = get_db()
    cur = db.execute('select locked from trans_lock where lock_id=1')
    return cur.fetchone()[0] 

def set_lock(locked, tid):
    db = get_db()
    db.execute('update trans_lock set locked=?, tid=? where lock_id=1',
        [locked, tid])
    db.commit()

def get_cur_tid():
    db = get_db()
    cur = db.execute('select tid from trans_lock where lock_id=1')
    return cur.fetchone()[0] 

def get_vote_result(tid):
    db = get_db()
    cur = db.execute('select * from transactions where \
        tid=? and type="get_vote_no"', (tid,))
    if cur.fetchone() != None:
        return 'abort'
    else:
        cur = db.execute('select count(*) from transactions where \
            tid=? and type="get_vote_yes"', (tid,))
        num_yeses = cur.fetchone()[0] 
        if num_yeses == len(get_peers()):
            return 'commit'
    return 'voting'

def tpc_prepare():
    myurl = get_myurl()
    peers = get_peers()

    while get_lock() == 1:
        pass

    tid = new_tid()
    set_lock(1, tid)
    for peer in peers:
        add_trans(tid, 'prepare', peer)
        params = {'tpc' : 'prepare', 'server' : myurl, 'tid' : tid}
        r = tpc_post(peer, params=params)

    # check vote results
    vote_result = 'voting'
    retries = 0
    while (vote_result != 'commit' and vote_result != 'abort'):
        retries += 1
        if retries % 100 == 0:
            tpc_post(peer, params=params)
        vote_result = get_vote_result(tid)
    return vote_result

def args2string(**kwargs):
    string = ''
    for key in kwargs.keys():
        string = string + str(key) + '=' + str(kwargs[key]) + ','
    return string.strip(',')

def string2args(string):
    if string == None:
        return None

    kwargs = {}
    tuples = string.split(',')
    for tuple in tuples:
        kv = tuple.split('=')
        kwargs[kv[0]] = kv[1]
    return kwargs

def tpc_commit(**kwargs):
    peers = get_peers()
    tid = get_cur_tid()
    myurl = get_myurl()
    file = None 
    str = args2string(**kwargs)
    params = kwargs
    files = None

    if kwargs['method'] == 'save_file':
        event_id = kwargs['event_id']
        filename = kwargs['filename']
        fullpath = os.path.join(app.config['UPLOAD_FOLDER'],event_id,filename)
        file = open(fullpath, 'rb')

    for server in peers:
        params['tpc'] = 'commit'
        params['server'] = myurl
        params['tid'] = tid
        if file != None:
            files = {'file' : file}
        add_trans(tid, "send_commit", server, str)
        tpc_post(server, params=params, files=files)
    
    done = 0
    retries = 0
    while done != 1:
        retries += 1
        db = get_db()
        cur = db.execute('select server from transactions where \
            type = ? and tid = ?', ["done_commit", tid])
        rows = cur.fetchall()
        # all slaves committed
        if len(rows) == len(peers):
            done = 1
        # resend to uncommitted servers every 20 tries
        elif retries % 100 == 0:
            for peer in peers:
                committed = 0
                for row in rows:
                    if peer == row.server:
                        committed = 1
                if committed == 0:
                    tpc_post(peer, params=params, files=files)     

    if file != None:
        file.close()
    # master locally
    add_trans(tid, "master_commit", myurl)
    set_lock(0, tid)


def tpc_abort():
    peers = get_peers()
    myurl = get_myurl()
    tid = get_cur_tid()
    for server in peers:
        params = {'tpc' : 'abort', 'tid' : tid, 'server' : myurl}
        tpc_post(server, params=params)
        add_trans(tid, "send_abort", server)
    # wait for every slave to finish
    done = 0
    retries = 0
    while done != 1:
        retries += 1
        db = get_db()
        cur = db.execute('select server from transactions where \
            type = ? and tid = ?', ["done_abort", tid])
        rows = cur.fetchall()
        # all slaves aborted
        if len(rows) == len(peers):
            done = 1
        # resend to unaborted servers every 20 tries
        elif retries % 20 == 0:
            for peer in peers:
                aborted = 0
                for row in rows:
                    if peer == row.server:
                        aborted = 1
                if aborted == 0:
                    tpc_post(peer, params=params)     
    # master locally
    add_trans(tid, "master_abort", myurl)
    set_lock(0, tid)

def tpc_vote(tid, master):
    myurl = get_myurl()
    ack = 'yes'
    if get_lock() == 1 and tid != get_cur_tid():
        ack = 'no'

    else:
        set_lock(1, tid)

    type = 'vote_' + ack
    add_trans(tid, type, master)

    params = {'tpc' : 'vote', 'tid' : tid, 'ack' : ack, 'server' : myurl}
    tpc_post(master, params=params)

def get_last_entry():
    db = get_db()
    cur = db.execute('select * from transactions order by column desc limit 1')
    res = cur.fetchone()
    return res

def find_entry(tid, type):
    db = get_db()
    cur = db.execute('select * from transactions where  \
        tid=? and type=?', [tid, type])
    res = cur.fetchone()
    return res


def redo():
    with app.app_context():
        tid = get_cur_tid()
        if tid == None:
            return
        
        if find_entry(tid, "master_commit") != None or \
            find_entry(tid, "master_abort") != None or \
            find_entry(tid, "slave_commit") != None or \
            find_entry(tid, "slave_abort") != None :
            set_lock(0, tid)
            return

        entry = find_entry(tid, "send_commit")
        if entry != None:
            arg_string = entry[4]
            kwargs = string2args(arg_string)
            tpc_commit(**kwargs)
            return
            
        #in all other cases, abort
        tpc_abort()


def tpc_post(server, params=None, files=None):
    try:
        requests.post(server, params=params, files=files)
    except Exception as e:
        print 'Exception in post: ', e, '!!!'
        pass


@app.route('/api', methods=['GET','POST'])
def api():
    if request.method == 'POST':
        myurl = get_myurl()
        tpc = request.args.get('tpc')
        server = request.args.get('server')
        tid = request.args.get('tid')

        peers = get_peers()
        if tpc == 'prepare':
            tpc_vote(tid, server)

        if tpc == 'vote':
            ack = request.args.get('ack')
            type = 'get_vote_' + ack
            add_trans(tid, type, server)

        if tpc == 'abort':
            params = {'tpc' : 'done', 'tid' : tid, 
                'server' : myurl, 'type' : 'abort'}
            tpc_post(server, params=params)
            add_trans(tid, "slave_abort", server)
            set_lock(0, tid)

        if tpc == 'commit':
            entry = find_entry(tid, 'slave_commit')
            if entry == None:
                method = request.args.get('method')
                if method == 'create_new_event':
                    event_name = request.args.get('event_name')
                    create_new_event(event_name)
                elif method == 'pub_event':
                    event_id = request.args.get('event_id')
                    event_id = int(event_id)
                    pub_event(event_id)
                elif method == 'abort_event':
                    event_id = request.args.get('event_id')
                    event_id = int(event_id)
                    abort_event(event_id)
                elif method == 'try_commit_event':
                    event_id = request.args.get('event_id')
                    event_id = int(event_id)
                    try_commit_event(event_id)
                elif method == 'vote':
                    event_id = request.args.get('event_id')
                    event_id = int(event_id)
                    username = request.args.get('username')
                    agree = request.args.get('agree')
                    vote(event_id, username, agree)
                elif method == 'save_file':
                    event_id = request.args.get('event_id')
                    event_id = int(event_id)
                    filename = request.args.get('filename')
                    file = request.files['file']
                    save_file(event_id, file, filename)
                add_trans(tid, "slave_commit", server)

            params = {'tpc' : 'done', 'tid' : tid, 
                'server' : myurl, 'type' : 'commit'}
            tpc_post(server, params=params)
            set_lock(0, tid)

        if tpc == 'done':
            type = request.args.get('type')
            type = 'done_' + type
            add_trans(tid, type, server)
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You were logged out')
    return redirect(url_for('login'))

if __name__ == '__main__':
    #app.run(debug=True)
    app.run(host='0.0.0.0', threaded=True)
    

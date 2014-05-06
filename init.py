import os
from picshare import init_db

if __name__ == '__main__':
    init_db()
    os.system('rm -rf /tmp/pics/*')

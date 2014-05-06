drop table if exists entries;
create table entries (
  event_id integer,
  username text not null,
  agree integer,
  unique(event_id, username) on conflict ignore
);

drop table if exists events;
create table events (
  event_id integer primary key autoincrement,
  name text unique not null,
  status text not null,
  timestamp integer
);

drop table if exists servers;
create table servers (
    id integer primary key,
    name text unique not null
);

drop table if exists transactions;
create table transactions (
    tid integer,
    type text not null,
    timestamp integer,
    server text not null,
    commit_args text,
    unique(tid, type, server) on conflict ignore
);

drop table if exists trans_lock;
create table trans_lock (
    lock_id integer primary key,
    locked    integer not null,
    tid     integer not null
);

insert into servers (id, name) values (1, "http://128.237.244.216:5000/api");
insert into servers (id, name) values (2, "http://128.2.134.20:5000/api");
insert into trans_lock (lock_id, locked, tid) values (1, 0, 0);

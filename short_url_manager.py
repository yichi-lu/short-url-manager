import sys
from datetime import datetime
import threading
from hashlib import sha256
import base64
from time import time
import sqlite3

import redis
from flask import Flask

DBNAME = 'shorturl.db'
DAYSECONDS = 60 * 60 * 24
WEEKSECONDS = DAYSECONDS * 7
lock = threading.Lock()
DEBUGGING = False

class TimedRun(object):
    """
    run a function at a specific time interval, repeatedly
    """
    def __init__(self, interval, f, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.f = f
        self.args = args
        self.kwargs = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        # schedule the next run, (repeat)
        self.start()
        self.f(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            # schedule the next run
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False


class ShortURLManager(object):
    """
    A short url manager
    """
    def __init__(self):
        self.conn = None        # database connection
        self.cur = None         # database cursor
        self.redis = None       # redis

        try:
            self.redis = self._get_redis()
        except Exception as ex:
            print(ex.message)
            sys.exit(1)

        try:
            self.conn = sqlite3.connect(DBNAME,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    isolation_level=None)
            self.cur = self.conn.cursor()
            self.cur.execute("CREATE TABLE if not exists urls (id INTEGER primary key, surl TEXT unique, lurl TEXT, accessed_day INTEGER, accessed_week INTEGER, accessed_all INTEGER, created FLOAT, modified FLOAT)")
            self.conn.commit()

            # update self.urls with data from database table
            self.cur.execute("SELECT * FROM urls") 
            rows = self.cur.fetchall()
            for row in rows:
                if DEBUGGING:
                    print("Existing url: {}".format(str(row)))
                if not self.redis.exists(row[1]):
                    url_dict = {
                            'short url': row[1],
                            'long url': row[2],
                            'accessed_day': row[3],
                            'accessed_week': row[4],
                            'accessed_all': row[5], 
                            'created': row[6], 
                            'modified': row[7]}
                    self.redis.hmset(row[1], url_dict)
            if DEBUGGING:
                print("Total number of existing urls: {}".format(len(rows)))

        except sqlite3.IntegrityError as err:
            print("Error connecting to database: {}".format(err))
            sys.exit(1)
        except sqlite3.Error as err:
            print("Error connecting to database: {}".format(err))
            sys.exit(1)

    def _get_redis(self):
        return redis.StrictRedis.from_url('redis://localhost:6379/1')

    def add_url(self, lurl):
        # for sqlite, objects created in a thread can only be used in that same thread.
        # have to create a new connection here
        if DEBUGGING:
            print("Adding a short url for {}".format(lurl))

        surl = self._long_to_short(lurl)
        url_dict = {
            'short url': surl,
            'long url': lurl,
            'accessed_day': 0,
            'accessed_week': 0,
            'accessed_all': 0, 
            'created': time(),
            'modified': time()}
        self.redis.hmset(surl, url_dict)

        now = time()
        self.conn = sqlite3.connect(DBNAME,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None)
        self.cur = self.conn.cursor()
        self.cur.execute("INSERT INTO urls(surl, lurl, accessed_day, accessed_week, accessed_all, created, modified) VALUES (?, ?, ?, ?, ?, ?, ?) ",
                (surl, lurl, 0, 0, 0, now, now))
        self.conn.commit()

        return surl

    def _long_to_short(self, lurl):
        start = 0
        end = 6

        # ensure short urls different even for the same long url
        url_digest_b64 = base64.b64encode(sha256((lurl
            + datetime.now().strftime("%Y-%m-%d %H:%M:%S:%f")).encode()).digest())
        while end < len(url_digest_b64):
            surl = url_digest_b64[start:end].replace(b'/', b'_').replace(b'+', b'_')
            if self.redis.hexists(surl, b'short url'):
                # ensure short url is unique
                start += 1
                end += 1
            else:
                break

        return surl

    def save_to_redis(self):
        url_dict = {'long url': self.lurl, 'short url': self.surl}
        self.redis.hmset(self.surl, url_dict)

    def reset_counts(self, surl, period):
        # reset accessed_day to 0 every 24 hours
        # reset accessed_week to 0 every 7 days
        if not self.redis.hexists(surl, b'short url'):
            if DEBUGGING:
                print("in reset_counts(). surl: {}".format(surl))
                print("urls keys: {}".format(str(mysurlman.redis.keys())))
            return

        # for sqlite, objects created in a thread can only be used in that same thread.
        # have to create a new connection here
        with lock:
            if period == 'DAY':
                url_dict = {'accessed_day': 0}
                self.redis.hmset(surl, url_dict)

                self.conn = sqlite3.connect(DBNAME,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    isolation_level=None)
                self.cur = self.conn.cursor()
                self.cur.execute("UPDATE urls SET accessed_day = ?, modified = ? WHERE surl = ? ",
                     (0, time(), surl))
                self.conn.commit()
            elif period == 'WEEK':
                url_dict = {'accessed_week': 0}
                self.redis.hmset(surl, url_dict)

                self.conn = sqlite3.connect(DBNAME,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    isolation_level=None)
                self.cur = self.conn.cursor()
                self.cur.execute("UPDATE urls SET accessed_day = ?, modified = ? WHERE surl = ? ",
                     (0, time(), surl))
                self.conn.commit()

        if DEBUGGING:
            print("Reset {} count for {} @ {}\n".format(period, surl, time()))

    def update_counts(self, surl, lurl, day, week, all_, born, end):
        # update accessed counts in DB once a short to long url redirection occurs
        # for sqlite, objects created in a thread can only be used in that same thread.
        # have to create a new connection here
        self.conn = sqlite3.connect(DBNAME,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None)
        self.cur = self.conn.cursor()
        self.cur.execute("INSERT OR REPLACE INTO urls(surl, lurl, accessed_day, accessed_week, accessed_all, created, modified) VALUES (?, ?, ?, ?, ?, ?, ?) ",
             (surl, lurl, day, week, all_, born, end))
        self.conn.commit()


app = Flask(__name__)

@app.route('/<url>')
def main(url):
    if DEBUGGING:
        print("url entered: {}".format(url))

    mysurlman = ShortURLManager()

    if len(url) == 15 and '-accessed' in url:          # url: xxxxxx-accessed
        # display accessed numbers
        start = time()
        surl = url[:6].encode()
        if DEBUGGING:
            print("surl: {}".format(surl))
            print("urls keys: {}".format(str(mysurlman.redis.keys())))
        if mysurlman.redis.exists(surl):
            url_dict = mysurlman.redis.hmget(surl, 'accessed_day', 'accessed_week',
            'accessed_all')
            return "{} accessed in: 24 hours: {}, past week: {}, all time: {}\n".format(
                    url[:6],
                    url_dict[0],
                    url_dict[1],
                    url_dict[2])
        else:
            return "not entry for " + url[:6] + " exists\n"

    elif len(url) != 6:
        # the (short) url hasn't been seen
        # Just create short url and save it
        # No redirection
        surl = mysurlman.add_url(url)

        if DEBUGGING:
            print("dayseconds: {}, weekseconds: {}".format(DAYSECONDS, WEEKSECONDS))

        # set accessed_day to 0 every 24 hours; accessed_week 7 days
        TimedRun(DAYSECONDS, mysurlman.reset_counts, surl, 'DAY')
        TimedRun(WEEKSECONDS, mysurlman.reset_counts, surl, 'WEEK')

        return "short url: {}\n".format(surl)

    else:
        # len(url) == 6. Redirection
        surl = url.encode()
        now = time()
        mysurlman.redis.hincrby(surl, 'accessed_day', 1)
        mysurlman.redis.hincrby(surl, 'accessed_week', 1)
        mysurlman.redis.hincrby(surl, 'accessed_all', 1)
        url_dict = {'modified': now}
        mysurlman.redis.hmset(surl, url_dict)
        url_dict = mysurlman.redis.hgetall(surl)
        lurl = url_dict[b'long url']
        end = time()
        mysurlman.update_counts(
                surl,
                lurl,
                url_dict[b'accessed_day'],
                url_dict[b'accessed_week'],
                url_dict[b'accessed_all'],
                url_dict[b'created'],
                end)
        return "short url: {}, long url: {}, in {}\n".format(surl.decode(), lurl, end - now)
    return ""


if __name__ == '__main__':

    if len(sys.argv) > 1 and 'debugging' in sys.argv[1]:
        DEBUGGING = True
    if len(sys.argv) > 2 and sys.argv[2].isdigit():
        DAYSECONDS = int(sys.argv[2])
    if len(sys.argv) > 3 and sys.argv[3].isdigit():
        WEEKSECONDS = int(sys.argv[3])
    app.run(debug=DEBUGGING, host='0.0.0.0', port=5000)


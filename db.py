import datetime
import hashlib
import logging
import re
import uuid

import tornado.gen
import rethinkdb as r

import utils



r.connect('localhost', 28015).repl()
db = r.db('nohuck')
utc = r.make_timezone('00:00')


### Settings ###
def settings_create():
    #db.table_create('settings').run()
    settings = {
        'id': 'settings',
        'motd': 'welcome to nohuck!',
        'about': 'https://github.com/csytan/nohuck',
        'cookie_secret': str(uuid.uuid4()),
        'youtube_api_key': None
    }
    id_counter = {
        'id': 'id_counter',
        'value': 4044
    }
    (db.table('settings')
        .insert([settings, id_counter])
        .run())
    return settings


def settings_get():
    return db.table('settings').get('settings').run()


def settings_save(settings):
    return (db.table('settings')
        .replace(settings)
        .run())

def generate_id():
    return (db.table('settings')
        .get('id_counter')
        .update({'value': r.row['value'].add(1) }, return_vals=True)
        .run()
        ['new_val']['value'])



### Users ###
def user_create(username, password):
    username = ''.join(c for c in username.lower()[:20] if c.isalnum() or c in '-_')
    user = {
        'id': username,
        'created': datetime.datetime.now(),
        'password': user_hash_password(password),
        'about': 'Nothing here yet.',
        'karma': 1
    }
    return (db.table('users')
        .insert(user, return_vals=True)
        .run()).get('new_val', None)


def user_get(username, password=None):
    return db.table('users').get(username).run()


def user_save(user):
    return (db.table('users')
        .get(user['id'])
        .replace(user, return_vals=True)
        .run())['new_val']


def user_hash_password(raw_password, n_iter=10000):
    assert len(raw_password) > 0 and len(raw_password) <= 20
    salt = str(uuid.uuid4()).replace('-', '')
    hsh = raw_password.encode('utf-8')
    for i in range(n_iter):
        hsh = hashlib.sha512(salt + hsh).hexdigest()
    return 'sha512$' + str(n_iter) + '$' + salt + '$' + hsh


def user_check_password(hashed_password, raw_password):
    algo, n_iter, salt, check_hsh = hashed_password.split('$')
    hsh = raw_password.encode('utf-8')
    for i in range(int(n_iter)):
        hsh = hashlib.sha512(salt + hsh).hexdigest()
    return hsh == check_hsh


def users_fetch():
    return list(db.table('users')
        .order_by(r.desc('karma'))
        .run())


### Videos ###
def video_create(title, text, thumbnail, video_ids, video_type, ip_likes=[], user_likes=[], user_id=None, feed=None):
    video = {
        'id': generate_id(),
        'created': datetime.datetime.now(utc),
        'updated': datetime.datetime.now(utc),
        'user_id': user_id,
        'feed': feed,
        'title': title,
        'text': text,
        'video_ids': video_ids,
        'video_type': video_type,
        'tags': [],
        'suggested_tags': [],
        'ip_likes': ip_likes,
        'user_likes': user_likes,
        'user_dislikes': [],
        'thumbnail': thumbnail,
        'n_comments': 0,
        'points': 0,
        'score': 0,
        'top_score': 0
    }
    video_update_scores(video)

    q = (db.table('videos')
        .insert(video)
        .run())
    return db.table('videos').get(video['id']).run()


def videos_get(id):
    return db.table('videos').get(id).run()


def video_save(video):
    video_update_scores(video)
    return (db.table('videos')
        .get(video['id'])
        .replace(video, return_vals=True)
        .run())['new_val']


def video_delete(id):
    result = (db.table('videos')
        .get(id)
        .delete()
        .run())
    return bool(result['deleted'])


def video_update_scores(video):
    def score(created, points, seconds_per_point=60*60*8):
        td = created - datetime.datetime(2013, 1, 1, tzinfo=utc)
        epoch_seconds = td.days * 86400 + td.seconds
        sign = 1 if points > 0 else -1 if points < 0 else 0
        return (points * seconds_per_point + epoch_seconds) / 1000.0 * sign

    def top_score(created, points):
        td = created - datetime.datetime(2013, 1, 1, tzinfo=utc)
        epoch_seconds = td.days * 86400 + td.seconds
        return float(str(points) + '.' + str(epoch_seconds))
    
    video['score'] = score(video['created'], video['points'])
    video['top_score'] = top_score(video['created'], video['points'])


def video_suggest_tags(video):
    # TODO: re-implement this
    text = (video['text']).lower()
    tag_first_words = {}
    self.suggested_tags = []
    for tag in group.tags:
        tag_spaced = tag.replace('-', ' ')
        if tag_spaced in text:
            self.suggested_tags.append(tag)
    for tag in self.suggested_tags:
        if tag in self.tags:
            self.suggested_tags.remove(tag)


def videos_fetch(tags, sort, page=None, after=None):
    q = db.table('videos')
    order = {'hot': 'score', 'top': 'top_score', 'new': 'created'}[sort]
    q = q.order_by(index=r.desc(order))
    for tag in tags:
        q = q.filter(r.row['tags'].contains(tag))
    if page:
        q = q.skip(page * 20)
    elif after:
        q = q.skip(10)
    q = q.limit(20)
    return list(q.run())
    
    
def videos_fetch_by_ids(video_ids):
    contains = None
    for id in video_ids:
        c = r.row['video_ids'].contains(id)
        contains = contains | c if contains else c
    
    return list(db.table('videos')
        .filter(contains)
        .run())


def videos_tag_counts(filter_tags=[]):
    counts = {}
    q = db.table('videos')
    for tag in filter_tags:
        q = q.filter(r.row['tags'].contains(tag))
    all_tags = (q.map(lambda video: video['tags'])
        .reduce(lambda left, right: left.add(right))
        .run())
    for tag in all_tags:
        if tag not in filter_tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def videos_edit_tag(tag, new_tag):
    return (db.table('videos')
        .filter(r.row['tags'].contains(tag))
        .update({
            'tags': r.row['tags'].difference([tag]).append(new_tag).distinct()
        })
        .run())


def videos_remove_tag(tag):
    return (db.table('videos')
        .filter(r.row['tags'].contains(tag))
        .update({
            'tags': r.row['tags'].difference([tag]).distinct()
        })
        .run())


def videos_submitted_by(username):
    return (db.table('videos')
        .order_by(index=r.desc('score'))
        .filter({'user_id': username})
        .run())


def videos_favorites(username):
    return (db.table('videos')
        .order_by(index=r.desc('score'))
        .filter(r.row['user_likes'].contains(username))
        .run())



### Comments ###
def comment_create(video, user, text, reply_to=None):
    if reply_to:
        reply_to = db.table('comments').get(reply_to).run()

    comment = {
        'created': datetime.datetime.now(utc),
        'user_id': user['id'],
        'video_id': video['id'],
        'reply_to': reply_to['id'] if reply_to else None,
        'points': 1,
        'text': text
    }
    return (db.table('comments')
        .insert(comment)
        .run())


def comments_for_video(video_id):
    return (db.table('comments')
        .order_by('created')
        .filter(r.row['video_id'] == video_id)
        .run())



### Feeds ###
def feed_create(id, url):
    feed = {
        'id': id,
        'updated': datetime.datetime.now(utc),
        'next_update': datetime.datetime.now(utc),
        'url': url,
        'active': True
    }
    return (db.table('feeds')
        .insert(feed)
        .run())
        

def feed_get(id):
    return db.table('feeds').get(id).run()


def feed_replace(id, feed):
    (db.table('feeds')
        .get(id)
        .delete()
        .run())
    return (db.table('feeds')
        .insert(feed, return_vals=True)
        .run())['new_val']


def feed_update(id):
    return (db.table('feeds')
        .get(id)
        .update({
            'updated': datetime.datetime.now(utc),
            'next_update': datetime.datetime.now(utc) + datetime.timedelta(hours=12)
        })
        .run())


def feed_delete(id):
    result = (db.table('feeds')
        .get(id)
        .delete()
        .run())
    return bool(result['deleted'])


def feeds_fetch():
    return list(db.table('feeds').run())


@tornado.gen.coroutine
def feeds_update(n=1):
    logging.info('updating feeds')

    feeds = list(db.table('feeds')
        .filter(r.row['next_update'] < datetime.datetime.now(utc))
        .limit(n)
        .run())
        
    requests = {f['id']: utils.video_ids_from_page(f['url']) for f in feeds}
    responses = yield requests
    
    for feed_id, video_ids in responses.items():
        dupe_videos = videos_fetch_by_ids([id[1] for id in video_ids])
        dupes = []
        for video in dupe_videos:
            dupes += video['video_ids']
        
        video_ids = [id for id in video_ids if id[1] not in dupes]
        youtube_ids = [id for vid_type, id in video_ids if vid_type == 'youtube']
        vimeo_ids = [id for vid_type, id in video_ids if vid_type == 'vimeo']

        if youtube_ids:
            video_data = yield utils.youtube_data_async(youtube_ids)
        elif vimeo_ids:
            video_data = yield utils.vimeo_data_async(vimeo_ids)
        else:
            video_data = None
        
        if video_data:
            datum = video_data[0]
            video = video_create(
                feed=feed_id,
                title=datum['title'],
                thumbnail=datum['thumbnail'],
                text=datum['description'],
                video_ids=[datum['id']],
                video_type=datum['video_type'])
        
        feed_update(feed_id)
        logging.info('updated feed: ' + feed_id)



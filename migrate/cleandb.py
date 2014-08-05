import rethinkdb as r
import json

import datetime

r.connect('localhost', 28015).repl()


def to_list(obj, key):
    value = obj[key]
    if not isinstance(value, list):
        value = value.replace("u'", '')
        value = value.replace('u"', '')
        value = value.replace("'", '')
        value = value.replace('"', '')
        value = value.strip('[').strip(']')
        obj[key] = [item.strip() for item in value.split(',') if item]

def to_float(obj, key):
    obj[key] = float(obj[key])

def to_bool(obj, key):
    value = obj[key]
    if not isinstance(value, bool):
        if value == 'False':
            value = False;
        elif value == 'True':
            value = True
        elif value == '':
            value = False
        else:
            raise Exception(value)
        obj[key] = value

def to_dt(obj, key):
    value = obj[key]
    if not isinstance(value, datetime.datetime):
        value = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')
        value = value.replace(tzinfo=r.make_timezone('00:00'))
        obj[key] = value

def delete(obj, key):
    if key in obj:
        del obj[key]


def replace(obj, table):
    t = r.db('nohuck').table(table)
    id = obj['id']
    if 'key' in obj:
        obj['id'] = obj['key']
        del obj['key']
        print t.insert(obj).run()
        print t.get(id).delete().run()
    else:
        print t.get(id).replace(obj).run()

def move_to_nohuck(table):
    r.db('nohuck').table_create(table).run()
    r.db('nohuck').table(table).insert(r.db('nohuck').table(table)).run()

def clean_videos():
    #feeds = {f['key']: f['name'].lower().replace(' ', '-') for f in r.db('nohuck').table('feeds').run()}
    for video in r.db('nohuck').table('videos').run():
        to_list(video, 'tags')
        to_list(video, 'suggested_tags')
        to_list(video, 'video_ids')
        to_list(video, 'ip_likes')
        to_list(video, 'user_likes')
        to_list(video, 'user_dislikes')
        to_float(video, 'top_score')
        to_float(video, 'score')
        to_bool(video, 'hot')
        to_bool(video, 'review')
        to_dt(video, 'created')
        to_dt(video, 'updated')
        if 'user' in video:
            video['user_id'] = video['user']
            del video['user']
        #if video['feed']:
        #    video['feed'] = feeds.get(video['feed'], None)
        #else:
        #    video['feed'] = None
        video['user_id'] = video.get('user_id', None)
        delete(video, 'group')
        replace(video, 'videos')


def clean_users():
    for user in r.db('nohuck').table('users').run():
        if 'group_karma' in user:
            del user['group_karma']
        if 'groups' in user:
            del user['groups']
        to_dt(user, 'created')
        to_dt(user, 'updated')
        replace(user, 'users')


def clean_feeds():
    for feed in r.db('nohuck').table('feeds').run():
        if 'key' in feed:
            del feed['key']
        to_dt(feed, 'created')
        to_dt(feed, 'next_update')
        to_dt(feed, 'updated')
        delete(feed, 'name')
        delete(feed, 'group')
        delete(feed, 'last_vid_added')
        delete(feed, 'bulk_add')
        replace(feed, 'feeds')


def clean_comments():
    for comment in r.db('nohuck').table('comments').run():
        if 'key' in comment:
            del comment['key']
        to_float(comment, 'points')
        if 'video' in comment:
            comment['video_id'] = int(comment['video'])
            del comment['video']
        if 'reply_to' in comment:
            del comment['reply_to']
        to_dt(comment, 'created')
        to_dt(comment, 'updated')
        replace(comment, 'comments')

#clean_videos()
#clean_users()
#clean_feeds()

clean_comments()

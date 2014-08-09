import datetime
import json
import logging
import os
import re
import subprocess
import sys
import urllib

import tornado.escape
import tornado.gen
import tornado.web
import tornado.ioloop

import utils
import db


settings = db.settings_get()
utils.youtube_api_key = settings['youtube_api_key']


class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        user_id = self.get_secure_cookie('user')
        if user_id:
            return db.user_get(user_id)

    def get_tag_counts(self):
        # TODO: cache tags in db module
        if not hasattr(self, 'tag_counts'):
            self._tag_counts = db.videos_tag_counts()
        return self._tag_counts

    def get_template_namespace(self):
        """Template globals"""
        namespace = super(BaseHandler, self).get_template_namespace()
        tag_counts = self.get_tag_counts()
        top_tags = sorted(tag_counts.items(), lambda a, b: b[1] - a[1])
        namespace.update({
            'version': '1',
            'link': self.link,
            'top_tags': top_tags,
            'motd': settings['motd'],
            'all_tags': tag_counts,
            'authorized': self.authorized,
            'relative_date': self.relative_date,
            'htmlify': self.htmlify
        })
        return namespace

    def authorized(self, action):
        actions = {
            'comment': 1,
            'edit_video': 10,
            'moderate': 40
        }
        if self.current_user:
            return self.current_user['karma'] >= actions[action]
        return False

    def authorize(self, action):
        if not self.current_user:
            raise tornado.web.HTTPError(401)
        if not self.authorized(action):
            raise tornado.web.HTTPError(403)

    def reload(self, save_form=False, message=None):
        if save_form:
            data = {}
            for arg in self.request.arguments:
                if arg not in ('_xsrf', 'password', 'password_repeat'):
                    data[arg] = self.get_argument(arg)
            self.set_secure_cookie('saved_form', json.dumps(data))
        if message:
            self.set_secure_cookie('message', message)
        self.redirect(self.request.path)

    def clear_saved_form(self):
        data = self.get_secure_cookie('saved_form')
        if data:
            self.clear_cookie('saved_form')
            return json.loads(data)
        return {}

    def clear_message(self):
        message = self.get_secure_cookie('message')
        if message:
            self.clear_cookie('message')
        return message

    def parse_tag_slug(self, tag_slug):
        all_tags = self.get_tag_counts()
        if not tag_slug:
            return []
        tags = tag_slug.split('+')
        for t in tags:
            if t not in all_tags:
                raise tornado.web.HTTPError(404)
        return tags
        
    def clean_tag(self, tag):
        return ''.join(c.lower() for c in tag if c.isalnum() or c == '-')[:40]

    ### Template helpers ###
    def link(self, page=None, tags=None, vid_id=None,
        query={}, exclude_tag=None):
        url = ''
        if page:
            url += '/' + page
        if tags:
            url += '/tags'
            tags = [t for t in tags if t != exclude_tag]
            if tags:
                url += '/' + '+'.join(tags)
        if vid_id:
            url += '/' + str(vid_id)
        if not url:
            url = '/'

        query = {key: val for key, val in query.items() if val}
        if query:
            url += '?' + urllib.urlencode(query)
        return url

    @staticmethod
    def relative_date(date):
        units = [
            (365 * 24 * 60 * 60, 'year'),
            (30 * 24 * 60 * 60, 'month'),
            (24 * 60 * 60, 'day'),
            (60 * 60, 'hour'),
            (60, 'minute')]
        seconds = (datetime.datetime.now(db.utc) - date).total_seconds()
        for unit in units:
            n = int(seconds / unit[0])
            if n >= 1:
                return str(n) + ' ' + unit[1] + ('s ago' if n >= 2 else ' ago')
        return str(seconds if seconds < 10 else int(seconds)) + ' seconds ago'

    @staticmethod
    def htmlify(text):
        text = tornado.escape.linkify(text, extra_params='rel="nofollow" target="_blank"')
        text = re.sub(r'(\r\n|\r|\n)', r'<br>', text)
        return text


class Index(BaseHandler):
    def get(self, tag_slug=None):
        sort = self.get_argument('sort', None)
        sort = sort if sort in ('new', 'top') else 'hot'
        tags = self.parse_tag_slug(tag_slug)
        page = self.get_argument('page', '')
        page = int(page) if page.isdigit() else 0
        videos = db.videos_fetch(tags, sort, page)
        next_page = page + 1 if len(videos) == 20 else None
        filter_tags = db.videos_tag_counts(tags).items() if tags else []
        filter_tags.sort(key=lambda x: x[0])
        filter_tags_top = sorted(filter_tags, key=lambda x: x[1], reverse=True)[:3]
        
        self.render('index.html',
            sort=sort,
            selected_tags=tags,
            tag_slug=tag_slug,
            filter_tags=filter_tags,
            filter_tags_top=filter_tags_top,
            videos=videos,
            page=page,
            next_page=next_page)

    def filter_tags(self, videos, selected_tags):
        total_vids = len(videos)
        if total_vids < 2:
            return []

        all_tags = []
        for v in videos:
            all_tags += v['tags']

        tags = []
        for tag in set(all_tags):
            if tag in selected_tags:
                continue
            n_vids = all_tags.count(tag)
            if n_vids < total_vids:
                tags.append((tag, n_vids))
        tags.sort(key=lambda x: x[0])
        return tags


class SignUp(BaseHandler):
    def get(self):
        self.render('sign_up.html')

    def post(self):
        bot = self.get_argument('bot', None)
        username = self.get_argument('username', None)
        password = self.get_argument('password', None)
        if bot or not username or not password:
            return self.reload(message='Please fill in your username and password.')
        username = ''.join(c for c in username.lower() if c.isalnum() or c in '-_')[:20]
        user = db.user_create(username=username, password=password)
        if not user:
            return self.reload(message='Sorry, that username is already in use.')
        self.set_secure_cookie('user', user['id'])
        self.redirect(self.link())



class Login(SignUp):
    def get(self):
        self.render('login.html')

    def post(self):
        username = self.get_argument('username', None)
        password = self.get_argument('password', None)
        next = self.get_argument('next', '/')
        if not username or not password:
            return self.reload()
        user = db.user_get(username)
        if not user or not db.user_check_password(user['password'], password):
            return self.reload(message='Incorrect Username or Password.')
        self.set_secure_cookie('user', user['id'])
        self.redirect(next if next.startswith('/') else '/')


class Logout(BaseHandler):
    def get(self):
        self.clear_cookie('user')
        self.redirect(self.link())


class User(BaseHandler):
    def get(self, id):
        user = db.user_get(id)
        if not user:
            raise tornado.web.HTTPError(404)
        self.render('user.html', user=user,
            favorites=db.videos_favorites(id),
            submitted=db.videos_submitted_by(id))

    @tornado.web.authenticated
    def post(self, id):
        action = self.get_argument('action', None)
        password = self.get_argument('password', None)
        password_repeat = self.get_argument('password_repeat', None)
        if action == 'about':
            self.current_user['about'] = self.get_argument('about', None)
        elif action == 'settings':
            if password == password_repeat:
                self.current_user['password'] = db.user_hash_password(password)
        db.user_save(self.current_user)
        self.reload()


class Tags(BaseHandler):
    def get(self):
        tag_counts = db.videos_tag_counts()
        tags = sorted(tag_counts.items(), key=lambda tag: tag[0])
        self.render('tags.html', tags=tags)

    @tornado.web.authenticated
    def post(self):
        self.authorize('moderate')
        action = self.get_argument('action', None)
        if action == 'edit_tag':
            tag = self.get_argument('tag')
            new_tag = self.get_argument('new_tag')
            new_tag = self.clean_tag(new_tag)
            db.videos_edit_tag(tag, new_tag)
        elif action == 'remove_tag':
            tag = self.get_argument('tag')
            db.videos_remove_tag(tag)
        self.reload()


class Video(BaseHandler):
    def get(self, id, tag_slug=None):
        video = db.videos_get(int(id))
        if not video:
            raise tornado.web.HTTPError(404)

        sort = self.get_argument('sort', None)
        sort = sort if sort in ('new', 'top') else 'hot'
        tags = self.parse_tag_slug(tag_slug)

        playlist = db.videos_fetch(tags, sort, after=video['id'])
        comments = db.comments_for_video(video['id'])
        self.render('video.html',
            sort=sort,
            selected_tags=tags,
            video=video,
            embed_src=self.embed_src,
            playlist=playlist,
            comments=self.nest_replies(comments),
            liked=self.request.remote_ip in video['ip_likes'])

    @staticmethod
    def nest_replies(comments):
        """Returns a dictionary mapping comment keys to their replies"""
        keys = {c['id']: [] for c in comments}
        for comment in comments:
            keys[comment['id']] = comment
            comment['replies'] = []
        for comment in comments:
            if comment['reply_to']:
                parent = keys.get(comment['reply_to'])
                if parent:
                    parent['replies'].append(comment)
        return [c for c in comments if not c['reply_to']]

    def render_comments(self, comments, nest=0):
        return self.render_string('_video_comment.html',
            comments=comments, nest=nest)

    @staticmethod
    def embed_src(id, video_type):
        if video_type == 'youtube':
            return 'http://www.youtube.com/embed/' + str(id) + '?autohide=1&amp;showinfo=0'
        elif video_type == 'vimeo':
            return 'http://player.vimeo.com/video/' + str(id)

    def post(self, id, tag_slug=None):
        video = db.videos_get(int(id))
        if not video:
            raise tornado.web.HTTPError(404)

        action = self.get_argument('action', None)
        if action == 'like':
            user_can_vote = (self.current_user and 
                self.current_user['id'] not in video['user_likes'])
            anon_can_vote = (self.request.remote_ip not in video['ip_likes'])
            mod_can_vote = (self.current_user and 
                self.current_user['id'] in ('csytan', 'sloepink'))
            if user_can_vote or mod_can_vote or anon_can_vote:
                if self.current_user:
                    video['user_likes'].append(self.current_user['id'])
                    video['user_likes'] = list(set(video['user_likes']))
                video['ip_likes'].append(self.request.remote_ip)
                video['ip_likes'] = list(set(video['ip_likes']))
                video['points'] += 1
                db.video_save(video)
                if self.current_user and video['user_id'] and video['points'] < 10:
                    db.user_add_karma(video['user_id'])
            return self.write('1')
        elif action == 'flag':
            self.authorize('moderate')
            video['n_likes'] -= 1
            db.video_save(video)
            return self.write('1')
        elif action == 'edit_tags':
            tags = self.get_argument('tags', '')
            tags = [self.clean_tag(t) for t in tags.split('|')]
            tags = tags + video['tags']
            tags = list(set(t for t in tags if t))
            video['tags'] = tags
            db.video_save(video)
        elif action == 'comment':
            self.authorize('comment')
            reply_to = self.get_argument('reply_to', None)
            text = self.get_argument('text', None)
            if text:
                db.comment_create(video, self.current_user, text, reply_to)
                video['n_comments'] += 1
                db.video_save(video)
        self.reload()


class AddOrEditVideo(BaseHandler):
    @tornado.web.authenticated
    def get(self, id=None, tag_slug=None):
        if id:
            video = db.videos_get(int(id))
            if not video:
                raise tornado.web.HTTPError(404)
        else:
            video = None
        self.render('add_or_edit_video.html', video=video)

    @tornado.web.authenticated
    @tornado.gen.coroutine
    def post(self, id=None, tag_slug=None):
        action = self.get_argument('action')
        urls = self.get_argument('urls', '')
        title = self.get_argument('title', '')
        text = self.get_argument('text', '')

        if action == 'remove':
            video = db.video_delete(int(id))
            if not video:
                raise tornado.web.HTTPError(404)
            self.set_secure_cookie('message', 'Video removed.')
            self.redirect(self.link())
            return

        if not urls or not title:
            self.reload(message='I cannot proceed without a URL and Title.', save_form=True)
            return

        video_ids = utils.video_ids_from_text(urls)
        if not video_ids:
            self.reload(message="I'm sorry, I only accept YouTube or Vimeo URLs.", save_form=True)
            return

        video_type = video_ids[0][0]
        for vid_type, vid_id in video_ids:
            if video_type != vid_type:
                self.reload(message='All URLs must be from the same site.', save_form=True)
                return

        video_ids = [vid_id for video_type, vid_id in video_ids]
        if video_type == 'youtube':
            video_data = yield utils.youtube_data_async(video_ids)
        elif video_type == 'vimeo':
            video_data = yield utils.vimeo_data_async(video_ids)

        if not video_data:
            self.reload(message="I couldn't validate the video, it might be private.", save_form=True)
            return


        valid_video_ids = (data['id'] for data in video_data)
        params = {
            'video_ids': [vid_id for vid_id in video_ids if vid_id in valid_video_ids],
            'title': title,
            'text': text,
            'video_type': video_data[0]['video_type'],
            'thumbnail': video_data[0]['thumbnail']
        }

        if id:
            video = db.videos_get(int(id))
            if not video:
                raise tornado.web.HTTPError(404)
            video.update(params)
            db.video_save(video)
        else:
            dupes = db.videos_fetch_by_ids(video_ids)
            if dupes:
                self.redirect(self.link(vid_id=dupes[0]['id']))
                return
            video = db.video_create(
                user_id=self.current_user['id'],
                ip_likes=[self.request.remote_ip],
                **params)
            db.user_add_karma(1)
        self.redirect(self.link(vid_id=video['id']))


class About(BaseHandler):
    def get(self):
        self.render('about.html',
            settings=db.settings_get(),
            users=db.users_fetch())

    @tornado.web.authenticated
    def post(self):
        self.authorize('moderate')
        settings = db.settings_get()
        settings['motd'] = self.get_argument('motd', None)
        settings['tagline'] = self.get_argument('tagline', None)
        settings['about'] = self.get_argument('about', None)
        db.settings_save(settings)
        self.reload(message="It has been done, m'lord.")


class Feeds(BaseHandler):
    def get(self):
        self.render('feeds.html', feeds=db.feeds_fetch())

    @tornado.web.authenticated
    def post(self):
        self.authorize('moderate')
        action = self.get_argument('action', None)
        id = self.get_argument('feed_id', None)
        new_id = self.get_argument('new_id', 'None')
        url = self.get_argument('url', None)
        
        if action == 'create':
            db.feed_create(id=id, url=url)
        elif action == 'edit':
            feed = db.feed_get(id)
            if not feed:
                raise tornado.web.HTTPError(404)
            feed['id'] = new_id
            feed['url'] = url
            f = db.feed_replace(id, feed)
            logging.info(str(f))
        elif action == 'remove':
            db.feed_delete(id)
        self.reload(message='Feeds updated')


class GitHubHook(BaseHandler):
    def post(self):
        # TODO: add hash verification
        logging.info(str(self.request))
        subprocess.call('git pull && sudo restart nohuck', shell=True)
        self.write('1')
    
    def check_xsrf_cookie(self):
        pass


routes = [
    (r'/', Index),
    (r'/login', Login),
    (r'/logout', Logout),
    (r'/sign_up', SignUp),
    (r'/@(.+)', User),
    (r'/submit', AddOrEditVideo),
    (r'/about', About),
    (r'/feeds', Feeds),
    (r'/_webhook', GitHubHook),
    (r'/tags', Tags),
    (r'/tags/(?P<tag_slug>[^\/]+)/(?P<id>\d+)', Video),
    (r'/tags/(?P<tag_slug>[^\/]+)/(?P<id>\d+)/edit', AddOrEditVideo),
    (r'/tags/(?P<tag_slug>[^\/]+)', Index),
    (r'/(?P<id>\d+)', Video),
    (r'/(?P<id>\d+)/edit', AddOrEditVideo)
]

config = {
    'template_path': 'templates',
    'static_path': 'static',
    'xsrf_cookies': True,
    'debug': True,
    'cookie_secret': settings['cookie_secret'],
    'login_url': '/login'
}


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    if 'prod' in sys.argv:
        logging.getLogger().setLevel(logging.ERROR)
        config['debug'] = False
    if 'cron' in sys.argv:
        tornado.ioloop.IOLoop.instance().run_sync(db.feeds_update)
    else:
        app = tornado.web.Application(routes, **config)
        app.listen(7000, address='127.0.0.1', xheaders=True)
        tornado.ioloop.IOLoop.current().start()



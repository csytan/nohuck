import collections
import json
import logging
import re
import urllib

import tornado.gen
import tornado.httpclient


youtube_api_key = ''


@tornado.gen.coroutine
def youtube_data_async(ids):
    """
    Example:
    https://www.googleapis.com/youtube/v3/videos?id=RtHKe4e-vnQ%2CnoGt4MV_S-E%2CqWABPASS_a0%2CeTseeqQhE5U%2CouAgZlmi6e8%2Ck2Ie0WNDXeo%2CGn2_I4vtAmA%2CpoiFKnVwMeQ%2CqSodpp0F8uI%2CdKaMH2vtO1o%2Cf7M-zR0nSUQ%2C3rDhytiplQg%2C0pU3fQgDi24%2C-8chZE7VwuE%2CvbT2iHaCR9k%2CxP1ggHeooos%2CAUIhlxzebsg%2CozL16c-dYuw%2CQ24kF4xs4yE%2C-kxfEdITlgk%2C-8bzEJHY5g0%2CiWIucMOu6Kk%2CBmxdhmT3BE8%2C0t27Ii9WfYs%2CnvZHRwDJDGs&part=snippet%2Cstatus%2Cstatistics&key=AIzaSyAA05TvZTthBsNJR7sEu0iQtX5Av2-h2ow
    """
    url = ('https://www.googleapis.com/youtube/v3/videos?id='
        + '%2C'.join(ids) +
        '&part=snippet%2Cstatus%2Cstatistics'
        '&key=' + youtube_api_key)
    logging.info('fetching: ' + url)

    client = tornado.httpclient.AsyncHTTPClient()
    response = yield client.fetch(url)

    if response.code == 200:
        data = json.loads(response.body)
    else:
        logging.info(response.body)
        raise tornado.gen.Return([])

    video_data = []
    for item in data['items']:
        if item['status']['embeddable'] and \
            item['status']['privacyStatus'] == 'public' and \
            item['snippet']['liveBroadcastContent'] != 'upcoming':
            video_data.append({
                'id': item['id'],
                'video_type': 'youtube',
                'title': item['snippet']['title'],
                'thumbnail': item['snippet']['thumbnails']['default']['url'],
                'description': item['snippet']['description']
            })
    raise tornado.gen.Return(video_data)


@tornado.gen.coroutine
def vimeo_data_async(ids):
    """
    Example:
    http://vimeo.com/api/v2/video/56556386.json
    """
    video_data = []
    requests = []

    for id in ids:
        url = 'http://vimeo.com/api/v2/video/' + str(id) + '.json'
        logging.info('fetching: ' + url)
        client = tornado.httpclient.AsyncHTTPClient()
        requests.append(client.fetch(url))

    responses = yield requests
    for response in responses:
        if response.code == 200:
            data = json.loads(response.body)
        else:
            logging.debug(response.body)
            raise tornado.gen.Return([])

        if data and data[0]['embed_privacy'] == 'anywhere':
            video_data.append({
                'id': str(data[0]['id']),
                'video_type': 'vimeo',
                'title': data[0]['title'],
                'thumbnail': data[0]['thumbnail_small'],
                'description': data[0]['description'].replace('<br />', '')
            })
    raise tornado.gen.Return(video_data)


@tornado.gen.coroutine
def video_ids_from_page(url):
    headers = {'User-Agent': 'nohuck.com bot by /u/csytan'} \
        if 'reddit.com' in url else {}
    client = tornado.httpclient.AsyncHTTPClient()
    response = yield client.fetch(url, headers=headers)
    if response.code == 200:
        video_ids = video_ids_from_text(response.body)
    else:
        logging.debug(response.body)
        video_ids = []
    raise tornado.gen.Return(video_ids)


def video_ids_from_text(text,
    youtube_re=re.compile(r'\/watch\?\S*v=([\w\-]+)'),
    youtube_re2=re.compile(r'youtu\.be\/([\w\-]+)'),
    youtube_re3=re.compile(r'youtube\.com\/embed\/([\w\-]+)'),
    vimeo_re=re.compile(r'vimeo\.com\/(\d+)'),
    vimeo_re2=re.compile(r'player\.vimeo\.com\/video\/(\d+)')):
    """
    Returns a list of YouTube and Vimeo video ids found in text,
    in the order they were found.
    """

    youtube_ids = youtube_re.findall(text) + \
        youtube_re2.findall(text) + \
        youtube_re3.findall(text)
    youtube_ids = list(collections.OrderedDict.fromkeys(youtube_ids))

    vimeo_ids = vimeo_re.findall(text) + vimeo_re2.findall(text)
    vimeo_ids = list(collections.OrderedDict.fromkeys(vimeo_ids))

    return [('youtube', id) for id in youtube_ids] + \
        [('vimeo', id) for id in vimeo_ids]



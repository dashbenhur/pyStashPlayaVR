import asyncio
from aiohttp import web
import logging
import os, re, math
from datetime import datetime

import stashapi.log as log
from stashapi.stashapp import StashInterface


##### config

# the port for this webserver
PORT = 6969

# the address at which this script, and PlayaVR, will access a Stash instance
STASH_SCHEME = "http"
STASH_HOST   = "192.168.86.56"
STASH_PORT   = "9999"

##### end config


API_BASE = "/api/playa/v2/"
STASH_BASE_URL = f"{STASH_SCHEME}://{STASH_HOST}:{STASH_PORT}"
stash = StashInterface({
    "scheme": STASH_SCHEME,
    "host":   STASH_HOST,
    "port":   STASH_PORT,
    "logger": log
})

def wrapJSON(data):
  return {
    "status": {
      "code": 1, "message": "ok"
    }, "data": data }


def stashBaseURL(request):
  return STASH_BASE_URL
  # scheme = request.url.scheme
  # host = request.url.host
  # base_url = f"{scheme}://{host}:9999"
  # return base_url

def getBaseURL(request):
  scheme = request.url.scheme
  host = request.url.host
  port = request.url.port

  base_url = f"{scheme}://{host}"
  if port and (scheme == 'http' and port != 80 or scheme == 'https' and port != 443):
      base_url += f":{port}"
  return base_url


#### URL handlers

routes = web.RouteTableDef()

@routes.get(API_BASE+'version')
async def webGetVersion(request):
  print('/version requested')
  return web.json_response(wrapJSON("1.0.0"))

@routes.get(API_BASE+'config')
async def webGetConfig(request):
  print('/config requested')
  return web.json_response(wrapJSON({
    "site_name": "pyPlaya",
    "actors": False,
    "categories": True,
    "studios": False,
    "categories_groups": False,
    "analytics": False
  }))

@routes.get(API_BASE+'categories')
async def webGetCategories(request):
  print('/categories requested')
  cats = [{'id': t['id'], 'title': t['name']} for t in stash.find_tags()]
  return web.json_response(wrapJSON(cats))

def timestamp(date_str_iso):
  return int(datetime.fromisoformat(date_str_iso).timestamp())

def preview_image(idd):
  return f"{STASH_BASE_URL}/scene/{idd}/screenshot"

def stream_url(idd):
  return f"{STASH_BASE_URL}/scene/{idd}/stream"

@routes.get(API_BASE+'videos')
async def webGetVideos(request):
  pageIndex = int(request.query['page-index'])
  pageSize  = int(request.query['page-size'])
  order     = request.query['order']
  direction = request.query['direction']
  cats      = request.query.get('included-categories', '')
  
  # categories
  if (cats == ''):
    cats = []
  else:
    cats = cats.split(',')

  # ordering
  order_str = 'id'
  if (order == 'title'):
    order_str = 'title'
  elif (order == 'release_date'):
    order_str = 'created_at'
  elif (order == 'popularity'):
    order_str = 'play_count'

  direction_str = 'ASC'
  if (direction == 'desc'):
    direction_str = 'DESC'

  #query
  scenes = stash._GQL("""
    query getScenes($perpage: Int, $page: Int, $order: String, $dir: SortDirectionEnum, $cats: [ID!]) {
      findScenes(filter: { per_page: $perpage, page: $page, sort: $order, direction: $dir }
           scene_filter: { tags: { modifier: INCLUDES_ALL, value: $cats } }) {
        count
        scenes {
          id
          title
          date
          created_at
          files {
            basename
          }
        }
      }
  }""", {
    'perpage': pageSize,
    'page': pageIndex+1,
    'order': order_str,
    'dir': direction_str,
    'cats': cats
    })['findScenes']
  
  scene_count = scenes['count']
  scenes = scenes['scenes']
  page_count = math.ceil(int(scene_count)/int(pageSize))

  scenes_output = []
  for s in scenes:
    s_out = {
      'id': s['id'],
      'title': s['title'],
      'preview_image': preview_image(s['id'])
    }

    # fix missing titles and dates
    if (s_out['title'] == ''):
      s_out['title'] = s['files'][0]['basename']
    if (s['date'] != None):
      s_out['release_date'] = timestamp(s['date'])
    else:
      s_out['release_date'] = timestamp(s['created_at'])


    scenes_output.append(s_out)
  
  sceneData = {
    "page_index": pageIndex,
    "page_size": pageSize,
    "page_total": page_count,
    "item_total": scene_count,
    "content": scenes_output
  }
  
  return web.json_response(wrapJSON(sceneData))

@routes.get(API_BASE+'video/{idd}')
async def webGetVideo(request):
  idd_str = request.match_info.get('idd', 'Invalid')
  if (idd_str == 'Invalid'):
    return web.HTTPBadRequest("invalid video id")
  idd = int(idd_str)

  s = stash._GQL("""
    query getScene($id: ID!) {
      findScene(id: $id) {
        id
        title
        release_date: created_at
        description: details
        duration: play_duration
      }
  }""", {'id': idd})['findScene']

  scene = {
    'id': s['id'],
    'title': s['title'],
    'release_date': timestamp(s['release_date']),
    'preview_image': preview_image(s['id']),
    'details': [{
      'type': 'full',
      'duration': s['duration'],
      'links': [{
        'is_stream': True,
        'is_download': False,
        'projection': '180',
        'stereo': 'LR',
        'url': stream_url(s['id']) 
      }]
    }]
  }

  return web.json_response(wrapJSON(scene))

@routes.get('/getvid/{idd}')
async def webGetVideo(request):
  print(request.url.host)
  idd_str = request.match_info.get('idd', 'Invalid')
  if (idd_str == 'Invalid'):
    raise web.HTTPBadRequest(reason="Invalid video ID")
  idd = int(idd_str)

  v = allVideoInfo[idd]
  file_path = v['filepath']
  print ('attempting to stream', file_path)

  if not os.path.exists(file_path):
    raise web.HTTPNotFound()

  file_size = os.path.getsize(file_path)
  range_header = request.headers.get('Range')

  if range_header:
    # Parse Range header (e.g., "bytes=0-1023")
    print('this request has a Range')
    try:
      range_parts = range_header.split('=')[1].split('-')
      start = int(range_parts[0])
      end = int(range_parts[1]) if range_parts[1] else file_size - 1
    except (ValueError, IndexError):
      raise web.HTTPBadRequest(reason="Invalid Range header")

    if not (0 <= start <= end < file_size):
      raise web.HTTPRequestedRangeNotSatisfiable()

    response = web.StreamResponse(
      status=206,  # Partial Content
      headers={
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Content-Length': str(end - start + 1),
        'Accept-Ranges': 'bytes'
      }
    )
    await response.prepare(request)

    with open(file_path, 'rb') as f:
      f.seek(start)
      chunk_size = 8192
      while start <= end:
        read_size = min(chunk_size, end - start + 1)
        chunk = f.read(read_size)
        if not chunk:
            break
        await response.write(chunk)
        start += len(chunk)
    return response
  else:
    print('this request does not have a Range')
    # Serve the entire file if no Range header is present
    return web.FileResponse(file_path)

  

app = web.Application()
app.add_routes(routes)
logging.basicConfig(level=logging.DEBUG)
web.run_app(app, port=PORT, access_log_format=" :: %r %s %T %t")

# async def handle(request):
#   name = request.match_info.get('name', "Anonymous")
#   text = "Hello, " + name
#   print('Request served!')
#   return web.Response(text=text)



# async def run_web_server():
#   app = web.Application()
#   app.add_routes([web.get('/api/playa/v2/version', webGetVersion),
#                   web.get('/{name}', handle)])
#   runner = web.AppRunner(app)
#   # await runner.setup()
#   # site = web.TCPSite(runner, 'localhost', 80)
#   # await site.start()

# loop = asyncio.get_event_loop()
# loop.create_task(run_web_server())
# loop.run_forever()
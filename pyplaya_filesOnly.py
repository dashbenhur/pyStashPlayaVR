import asyncio
from aiohttp import web
import logging
import os, re

##### config
PORT = 80
API_BASE = "/api/playa/v2/"
FILES_BASE = "/Users/scott/Desktop/Private VR"
ALLOWED_EXTENSIONS = ["mp4", "mkv"]
##### helpers

def wrapJSON(data):
  return {
    "status": {
      "code": 1, "message": "ok"
    }, "data": data }

def getSubDirNames(rootDir):
  subDirs = []
  for root, dirs, files in os.walk(rootDir):
      subDirRelPath = os.path.relpath(root, rootDir)
      if (subDirRelPath == "."):
        subDirRelPath = "Default"
      subDirs.append(subDirRelPath)
  return subDirs

def safeCatName(catName):
  return re.sub(r"[^a-zA-Z0-9]", "-", catName).lower()

def getBaseURL(request):
  scheme = request.url.scheme
  host = request.url.host
  port = request.url.port

  base_url = f"{scheme}://{host}"
  if port and (scheme == 'http' and port != 80 or scheme == 'https' and port != 443):
      base_url += f":{port}"
  return base_url

# make extns list more useable
ALLOWED_EXTENSIONS = ["."+extn.lower() for extn in ALLOWED_EXTENSIONS]
def hasAllowedExtension(filename):
  for extn in ALLOWED_EXTENSIONS:
    if (filename.lower().endswith(extn)):
      return True
  return False

def getVideoInfo(idd, cat, filename):
  if (cat == "Default"):
    cat = ""
  localPath = os.path.join(cat, filename)
  globalPath = os.path.join(FILES_BASE,localPath)
  return {
    "id": idd,
    "name": filename,
    "release_date": int(os.path.getmtime(globalPath)),
    "filepath": globalPath
  }

def getAllVideoInfo(rootDir):
  allInfo = []
  for root, dirs, files in os.walk(rootDir):
      subDirRelPath = os.path.relpath(root, rootDir)
      if (subDirRelPath == "."):
        subDirRelPath = "Default"
      for filename in files:
        if (hasAllowedExtension(filename)):
          allInfo.append(getVideoInfo(len(allInfo), subDirRelPath, filename))
  return allInfo

allVideoInfo = getAllVideoInfo(FILES_BASE)

def getVideosInfoToPublish(v):
  return {
    'id': str(v['id']),
    'title': v['name'],
    'release_date': v['release_date']
  }

def getFullVideoInfo(idd, v, base_url):
  return {
    'id': idd,
    'title': v['name'],
    'release_date': v['release_date'],
    'details': [{
      'type': 'full',
      'links': [{
        'is_stream': True,
        'is_download': False,
        'projection': '180',
        'stereo': 'LR',
        'url': base_url+'/getvid/'+str(idd)
      }]
    }]
  }

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
  subDirs = getSubDirNames(FILES_BASE)
  cats = [{"id": safeCatName(cat), "name": cat} for cat in subDirs]
  return web.json_response(wrapJSON(cats))

@routes.get(API_BASE+'videos')
async def webGetVideos(request):
  pageIndex = int(request.query['page-index'])
  pageSize  = int(request.query['page-size'])
  # order     = request.query['order']
  # direction = request.query['direction']
  
  videos = allVideoInfo[pageIndex*pageSize:(pageIndex+1)*pageSize]
  videos = [getVideosInfoToPublish(v) for v in videos]

  videoData = {
    "page_index": pageIndex,
    "page_size": pageSize,
    "page_total": len(videos),
    "item_total": len(allVideoInfo),
    "content": videos
  }
  return web.json_response(wrapJSON(videoData))

@routes.get(API_BASE+'video/{idd}')
async def webGetVideo(request):
  print(request.url.host)
  idd_str = request.match_info.get('idd', 'Invalid')
  if (idd_str == 'Invalid'):
    return web.send_response("invalid video id")
  idd = int(idd_str)

  v = allVideoInfo[idd]
  v_data = getFullVideoInfo(idd, v, getBaseURL(request))
  return web.json_response(wrapJSON(v_data))

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
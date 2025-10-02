This is a python script that runs a webserver that you can point a PlayaVR app at, and it will serve videos to it, either from a local directory (`pyplaya_filesOnly.py`) or with metadata from a stash server (`pyplaya_stash.py`).

No command-line arguments at the moment, you'll just need to configure the address of your Stash instance, in the config section at the top of the python script. Don't use "localhost" to point to the Stash instance, because then your VR device running PlayaVR will try to access Stash using "localhost".

## Requirements:
- `aiohttp`
- `stashapi` (for Stash version)

## Running
`python3 pyplaya_stash.py`
import argparse
import logging

import uvicorn

from .api import create_api, create_downloads, repository_from_env

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["api", "downloads", "init"])
parser.add_argument("--host", default="0.0.0.0")
parser.add_argument("--port", type=int, default=8080)
parser.add_argument("--import-repo")
args = parser.parse_args()
logging.basicConfig(level=logging.INFO)
if args.command == "init":
    repository_from_env().initialize(args.import_repo)
else:
    app = create_api() if args.command == "api" else create_downloads()
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)

"""Bounded actual installed Hermes API adapter; never starts the full gateway.

Connection credentials exist only in an owner-private temporary file and memory.
The existing Hermes home supplies normal auth/config; this script never edits it.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sys
import time

if sys.flags.optimize:
    raise SystemExit("optimized_python_unsupported: run without -O or -OO")


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


async def run(args):
    home=Path.home()/'.hermes'
    protected=[home/'.env',home/'config.yaml',home/'orpheus/review-presets.yaml',home/'orpheus/review-deployment.yaml']
    protected.extend(Path(path) for path in args.protected_file)
    before={str(path):fingerprint(path) for path in protected}
    directory=Path(args.output_dir)
    sys.path.insert(0,str(Path(args.hermes_source).resolve()))
    import hermes_bootstrap  # installed entrypoint bootstrap
    from gateway.run import _load_gateway_config
    from hermes_cli.fallback_config import get_fallback_chain
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    import aiohttp
    # gateway.run may re-exec under Hermes managed Python; create no files before it.
    directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    directory.chmod(0o700)
    config=_load_gateway_config()
    if get_fallback_chain(config):
        raise RuntimeError('effective_provider_fallback_enabled')
    model=config.get('model',{})
    if not isinstance(model,dict) or not model.get('default') or not model.get('provider'):
        raise RuntimeError('explicit_default_model_provider_required')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port=reservation.getsockname()[1]
    token=secrets.token_hex(32)
    adapter=APIServerAdapter(PlatformConfig(enabled=True,extra={'host':'127.0.0.1','port':port,'key':token}))
    stopped=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(sig,stopped.set)
    connection=directory/'connection.json'
    started=False
    try:
        if not await adapter.connect():
            raise RuntimeError('api_adapter_connect_failed')
        started=True
        url=f'http://127.0.0.1:{port}'
        async with aiohttp.ClientSession() as client:
            async with client.get(url+'/health',timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status!=200:raise RuntimeError('api_adapter_health_failed')
        with connection.open('x') as file:
            os.chmod(connection,0o600)
            json.dump({'url':url,'token':token,'model':model['default'],'provider':model['provider'],'fallback_disabled':True,'pid':os.getpid()},file)
        print(json.dumps({'ready':True,'connection_file':str(connection),'bounded_seconds':args.seconds}),flush=True)
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline and not stopped.is_set() and not (directory/'stop').exists():
            try:await asyncio.wait_for(stopped.wait(),timeout=1)
            except asyncio.TimeoutError:pass
    finally:
        if started:await adapter.disconnect()
        connection.unlink(missing_ok=True)
        after={str(path):fingerprint(path) for path in protected}
        summary={'stopped':True,'protected_configuration_files':len(protected),'protected_configuration_unchanged':before==after,'real_adapter':True,'full_gateway_started':False}
        (directory/'bootstrap-receipt.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary),flush=True)
        if before!=after:raise RuntimeError('protected_configuration_changed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-source',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--protected-file',action='append',default=[])
    parser.add_argument('--seconds',type=int,default=600)
    args=parser.parse_args()
    if not 1<=args.seconds<=900:parser.error('seconds must be between 1 and 900')
    asyncio.run(run(args))


if __name__=='__main__':main()

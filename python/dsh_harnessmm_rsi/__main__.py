from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .runner import run_lifecycle, route_policy, export_policy, verify_upstream


def main():
    parser=argparse.ArgumentParser(description='Native DeepSeek Harness extension RSI; model calls occur only in train')
    commands=parser.add_subparsers(dest='command',required=True)
    train=commands.add_parser('train')
    train.add_argument('--corpus',required=True);train.add_argument('--output',required=True)
    train.add_argument('--dsh-bin',default='/home/sushi/.local/bin/dsh');train.add_argument('--dsh-home',required=True)
    train.add_argument('--profile',default='harnessmm-training');train.add_argument('--provider',required=True);train.add_argument('--model',required=True);train.add_argument('--reasoning-effort',default=None)
    train.add_argument('--iterations',type=int,default=2);train.add_argument('--timeout',type=float,default=300)
    train.add_argument('--sdk-patch');train.add_argument('--node',default='node');train.add_argument('--sdk-module');train.add_argument('--meter-module')
    route=commands.add_parser('route');route.add_argument('--policy',required=True)
    inspect=commands.add_parser('inspect');inspect.add_argument('path')
    export=commands.add_parser('export');export.add_argument('policy');export.add_argument('--output',required=True)
    commands.add_parser('doctor')
    args=parser.parse_args()
    if args.command=='route': print(json.dumps(route_policy(args.policy,sys.stdin.read()),ensure_ascii=False))
    elif args.command=='train':
        report=run_lifecycle(args.corpus,args.output,dsh=args.dsh_bin,dsh_home=args.dsh_home,model=args.model,provider=args.provider,iterations=args.iterations,timeout=args.timeout,sdk_patch=args.sdk_patch,profile=args.profile,node=args.node,sdk_module=args.sdk_module,meter_module=args.meter_module,reasoning_effort=args.reasoning_effort)
        print(json.dumps({'state':report['state'],'output':str(Path(args.output).resolve())}))
    elif args.command=='inspect':
        path=Path(args.path);path=path/'report.json' if path.is_dir() else path
        print(json.dumps(json.loads(path.read_text()),indent=2))
    elif args.command=='export': export_policy(args.policy,args.output)
    elif args.command=='doctor': print(json.dumps({'upstream':verify_upstream(),'model_calls':0,'runtime':'official_deepseek_harness_sdk'}))
    return 0


if __name__=='__main__': raise SystemExit(main())

#!/bin/bash
# 用法: ./crawl.sh URL1 URL2 URL3 ...
# 或者: ./crawl.sh  （不带参数会提示输入）

cd /Users/akb/.qoderwork/tipsy-crawler
source venv/bin/activate

if [ $# -eq 0 ]; then
  echo "用法: ./crawl.sh <角色URL> [角色URL2] ..."
  echo "示例: ./crawl.sh https://tipsy.chat/chat/1781685750090356919"
  exit 1
fi

python -m tipsy_crawler.main -c config.yaml \
  --char-urls "$@" \
  --wash-images --wash-text --infer-json

#!/bin/bash
# Tipsy Crawler 一键运行脚本
# 双击即可运行，不消耗 QoderWork credits

cd /Users/akb/.qoderwork/tipsy-crawler
source venv/bin/activate

echo "========================================"
echo "  Tipsy Crawler"
echo "========================================"
echo ""
echo "请选择模式："
echo "  1) 按作者爬取（扫描作者所有角色）"
echo "  2) 指定角色 URL 爬取（完整流水线）"
echo "  3) 自定义命令"
echo ""
read -p "输入选项 (1/2/3): " choice

case $choice in
  1)
    read -p "作者主页 URL: " author_url
    read -p "爬取数量 (默认3): " max_chars
    max_chars=${max_chars:-3}
    echo ""
    echo "开始爬取..."
    python -m tipsy_crawler.main -c config.yaml \
      --authors "$author_url" \
      -n "$max_chars" \
      --wash-images --wash-text --infer-json
    ;;
  2)
    echo "输入角色 URL（每行一个，输入空行结束）："
    urls=""
    while IFS= read -r line; do
      [ -z "$line" ] && break
      urls="$urls $line"
    done
    echo ""
    echo "开始爬取..."
    python -m tipsy_crawler.main -c config.yaml \
      --char-urls $urls \
      --wash-images --wash-text --infer-json
    ;;
  3)
    read -p "输入完整命令: " cmd
    eval "$cmd"
    ;;
  *)
    echo "无效选项"
    ;;
esac

echo ""
echo "完成！按回车退出..."
read

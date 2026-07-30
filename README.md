# Tipsy Crawler

Tipsy.chat 角色卡爬虫工具 — 扫描作者主页 → 抓取角色公共页 → 清洗图片/文本 → 反推生成 Tavern V2 角色卡 JSON。

## Features

- **Author scanning**: 批量扫描作者主页，提取所有角色卡片
- **Character scraping**: 支持两种页面类型 — 结构化记忆页（BACKSTORY/OPENING 标记）和聊天记录页
- **Image washing**: 通过 MuleRouter API (qwen-image-edit-spicy) 对封面图做风格化修改，自动适配角色人设
- **Text washing**: LLM 替换角色名、改写文本，保留 {{User}}/{{Char}} 占位符
- **JSON inference**: 从清洗后的文本或聊天记录反推完整的 Tavern AI chara_card_v2 格式角色卡
- **Configurable prompts**: 所有 LLM prompt 在 `config.yaml` 中集中管理，改 YAML 即可调整

## Quick Start

```bash
# 1. Clone & install
git clone https://github.com/YOUR_USERNAME/tipsy-crawler.git
cd tipsy-crawler
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .

# 2. Install browser
playwright install chromium

# 3. Configure API keys
cp .env.example .env
# Edit .env — fill in DEEPSEEK_API_KEY and MULEROUTER_API_KEY

# 4. Run!
tipsy-crawler -c config.yaml --wash-images --wash-text --infer-json -n 3
```

## Usage

### Basic scrape (no API keys needed)

```bash
tipsy-crawler -n 3
```

Only downloads raw text and cover images. No LLM or image API calls.

### Full pipeline

```bash
tipsy-crawler -c config.yaml --wash-images --wash-text --infer-json -n 5
```

Scans authors → scrapes characters → washes images → washes text → generates Tavern V2 JSON.

### Chat page scraping

```bash
tipsy-crawler -c config.yaml --chat-urls "https://tipsy.chat/chat/12345" "https://tipsy.chat/chat/67890" --infer-from-chat
```

Manually provide chat URLs → scrape chat messages → output MD files → LLM reverse-engineers character cards.

### Direct character URL mode (recommended)

```bash
tipsy-crawler -c config.yaml \
  --char-urls "https://tipsy.chat/chat/12345" "https://tipsy.chat/chat/67890" \
  --wash-images --wash-text --infer-json
```

Pass character page URLs directly → full pipeline: fetch memories + chat records → download cover → wash image → wash text → generate Tavern V2 JSON. Works with any character URL format (`/chat/12345`, `/chat/12345/public`).

### CLI options

| Flag | Description |
|---|---|
| `-c, --config` | Path to config.yaml |
| `-o, --output` | Output directory |
| `-n, --max-chars` | Max characters per author (default: 3) |
| `-a, --authors` | Override author profile URLs |
| `--char-urls` | Character page URLs for full pipeline processing |
| `--chat-urls` | Chat page URLs for chat scraping mode |
| `--infer-from-chat` | Run LLM inference after chat scraping |
| `--wash-images` | Enable image washing (needs MuleRouter API key) |
| `--wash-text` | Enable text washing (needs LLM API key) |
| `--infer-json` | Enable JSON inference (needs LLM API key) |
| `--no-headless` | Show browser window (for debugging) |

## Output Structure

```
output_dir/
├── authors.json
└── {author_id}/
    └── {chat_id}/
        ├── raw/
        │   ├── cover_image.gif      # Original cover
        │   ├── backstory.txt        # Extracted backstory
        │   ├── opening.txt          # Extracted opening message
        │   └── meta.json            # Raw metadata
        ├── cover_image_washed.jpg   # Washed cover image
        ├── washed.json              # Washed text (name replaced, rewritten)
        └── character.json           # Tavern V2 character card
```

## Configuration

### API Keys (.env)

| Key | Required | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | For text/JSON tasks | Name generation, text washing, JSON inference |
| `MULEROUTER_API_KEY` | For image washing | AI image editing via qwen-image-edit-spicy |
| `OPENAI_API_KEY` | Optional | Alternative LLM provider |
| `ANTHROPIC_API_KEY` | Optional | Alternative LLM provider |

### config.yaml

- **providers**: LLM provider configurations (base URL, API key, model)
- **tasks**: Map each task (name_generation, text_wash, infer_json) to a provider
- **mule_router**: MuleRouter image editing settings
- **crawler**: Concurrency, output directory, browser settings
- **prompts**: All LLM prompts — edit here to customize behavior

See `config.yaml` for full reference with inline comments.

### Customizing Prompts

All prompts are in `config.yaml` under the `prompts:` section. Each task has a `_system` and `_user` pair:

```yaml
prompts:
  wash_text_system: |
    You are a creative editor...
  wash_text_user: |
    Old name: {original_name}
    New name: {new_name}
    ...
```

Available placeholders: `{original_name}`, `{new_name}`, `{name}`, `{backstory}`, `{opening}`, `{tags}`, `{image_filename}`, `{character_name}`, `{chat_text}`.

## Architecture

```
main.py          CLI entry point
pipeline.py      End-to-end orchestration
scraper.py       Playwright browser scraping (author pages, character pages, chat pages)
downloader.py    Concurrent image downloads with Cloudflare handling
llm.py           LLM client (OpenAI-compatible, supports DeepSeek/GPT/Claude)
image_wash.py    MuleRouter async image editing with polling
config.py        YAML + env var configuration
models.py        Pydantic data models
```

## Requirements

- Python 3.9+
- Chromium browser (installed via `playwright install chromium`)

## License

MIT

# Boss直聘远程控制

Chrome 扩展 + Python 服务，远程控制 Boss直聘页面，支持 JS 远程执行、元素坐标查询、标签管理。

## 安装

### Python 服务

```bash
uv sync
```

### Chrome 扩展

```bash
cd extension
npm install
npm run build
```

然后在 Chrome 中加载 `extension/dist/` 目录。

## 使用

```bash
# 启动服务
uv run python -m bzauto

# 或使用 CLI 入口
boss-server
boss-scrape
boss-analyze
```

## 开发

### 构建扩展

```bash
cd extension
npm run build
```

### 运行 Python 类型检查

```bash
uv run python -c "from bzauto.protocol.types import TabInfo"
```

### 运行 TypeScript 类型检查

```bash
cd extension
npx tsc --noEmit
```
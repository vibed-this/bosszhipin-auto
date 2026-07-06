# BrowserSession 滚动 API

## `scroll_pagedown`

```python
async def scroll_pagedown(*, at_x=None, at_y=None, presses=3)
```

发送真实 PageDown 键盘事件到 QWebEngineView，触发页面/容器的懒加载。

- `presses` — 重复次数（控制滚动幅度）
- `at_x/at_y` — 当前未用于定位，但保留接口一致

内部调用 `events.send_key(view, Qt.Key_PageDown, presses=presses)`。

## `scroll_wheel`

```python
async def scroll_wheel(dy, *, at_x=None, at_y=None, presses=1)
```

发送滚轮事件到指定坐标。

- `dy` — 滚动量（正=上，负=下），单位角度增量（120 = 1 格）
- `at_x/at_y` — 视口坐标（CSS 像素），来自 `bbox()` 的 `cx/cy`
- `presses` — 重复次数

## `mouse_move`

```python
async def mouse_move(x, y)
```

发送鼠标移动事件到指定坐标，用于 hover/聚焦元素。

## `click`

```python
async def click(x, y)
```

在坐标 `(x, y)` 发送鼠标点击（Move + Press + Release）。

## `bbox`

```python
async def bbox(select, *, filter=None, timeout=30.0) -> dict | None
```

返回元素在视口中的包围盒：`{x, y, w, h, cx, cy}`。`cx/cy` 是中心点，可直接用于 `click/mouse_move/scroll_wheel`。

## `eval_js`

```python
async def eval_js(code, *, timeout=30.0) -> Any
```

在页面 MAIN world 执行 JS，返回 JSON 反序列化结果。

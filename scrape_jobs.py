"""精炼抓取 BOSS 直聘职位数据 + 定位 tab 元素"""

import asyncio
import json
import logging

import uvicorn
from server import TabRegistry, RemoteSession, create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("scraper")


SCRAPE_JOBS = r"""
// DOM 结构已知:
// LI.job-card-box
//   DIV.job-info
//     DIV.job-title.clearfix > A.job-name (title) + SPAN.job-salary (salary)
//     UL.tag-list > LI[0]=experience, LI[1]=education, LI[2..n]=tech tags
//   DIV.job-card-footer
//     A.boss-info > SPAN.boss-name (company)
//     SPAN.company-location (area)

const cards = document.querySelectorAll('li.job-card-box');

const jobs = Array.from(cards).map(card => {
  const title  = card.querySelector('.job-name')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const salary = card.querySelector('.job-salary')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const company = card.querySelector('.boss-name')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const area   = card.querySelector('.company-location')?.textContent?.replace(/\s+/g, ' ').trim() || '';

  // tag-list 的 li 子元素: [经验, 学历, 标签...]
  const tagItems = Array.from(card.querySelectorAll('.tag-list > li'));
  const experience = tagItems[0]?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const education  = tagItems[1]?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const techTags   = tagItems.slice(2).map(el => el.textContent?.replace(/\s+/g, ' ').trim()).filter(Boolean);

  const link = card.querySelector('a.job-name')?.href || '';

  return { title, company, area, experience, education, tags: techTags, salary, link };
});

return {
  url: location.href,
  title: document.title,
  total: jobs.length,
  jobs,
};
"""

LOCATE_TAB = r"""
// "前端/移动开发(长沙)" tab
const tab = document.querySelector('a.expect-item');
if (!tab) return { error: 'tab not found' };

const rect = tab.getBoundingClientRect();
const text = (tab.textContent || '').replace(/\s+/g, ' ').trim();

// 获取样式
const style = window.getComputedStyle(tab);
const display = style.display;
const visibility = style.visibility;

// 判断是否在可视区域
const inViewport = rect.top >= 0 && rect.left >= 0 &&
  rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
  rect.right <= (window.innerWidth || document.documentElement.clientWidth);

return {
  text,
  className: tab.className,
  viewport: { x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) },
  inViewport,
  display,
  visibility,
  computed: {
    position: style.position,
    overflow: style.overflow,
    zIndex: style.zIndex,
  },
  // 外层容器
  container: tab.parentElement?.className || '',
  // 相对 document 的偏移 (滚动修正)
  docOffset: {
    x: Math.round(rect.left + window.scrollX),
    y: Math.round(rect.top + window.scrollY),
  },
};
"""


async def main():
    host, port = "127.0.0.1", 8765
    registry = TabRegistry()
    session = RemoteSession(registry)
    app = create_app(registry)

    connected = asyncio.Event()
    registry.on("tab_connected", lambda m: (log.info("连接: %s", m["tab"]["tab_id"][:8]), connected.set()))

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    server_task = asyncio.create_task(server.serve())

    try:
        await asyncio.wait_for(connected.wait(), timeout=120.0)
        tab = registry.tabs[0]
        tab_id = tab["tab_id"]
        log.info("使用标签: %s", tab_id[:8])

        # 1. 精炼抓取
        log.info("抓取职位数据...")
        data = await session.execute(tab_id, SCRAPE_JOBS)
        jobs = data.get("jobs", [])
        print(f"\n{'=' * 60}")
        print(f"职位数据 ({data.get('total', len(jobs))} 条)")
        print(f"{'=' * 60}")
        for j in jobs:
            tags_str = ' '.join(j['tags'])
            print(f"\n  {j['title']}")
            print(f"    公司: {j['company']}  |  地点: {j['area']}")
            print(f"    经验: {j['experience']}  |  学历: {j['education']}")
            if tags_str:
                print(f"    技能: {tags_str}")
            print(f"    链接: {j['link']}")

        # 2. 定位 tab
        log.info("定位 tab...")
        tab_info = await session.execute(tab_id, LOCATE_TAB)
        print(f"\n{'=' * 60}")
        print("Tab 定位：前端/移动开发(长沙)")
        print(f"{'=' * 60}")
        print(f"  文本: {tab_info.get('text')}")
        print(f"  class: {tab_info.get('className')}")
        vp = tab_info.get('viewport', {})
        print(f"  视口位置: left={vp.get('x')}, top={vp.get('y')}, "
              f"width={vp.get('width')}, height={vp.get('height')}")
        print(f"  在视口中: {tab_info.get('inViewport')}")
        doc = tab_info.get('docOffset', {})
        print(f"  文档位置: x={doc.get('x')}, y={doc.get('y')}")
        print(f"  容器: {tab_info.get('container')}")

        # 3. 坐标查询
        log.info("查询屏幕坐标...")
        try:
            coords = await session.get_element_coordinates(tab_id, 'a.expect-item')
            print(f"\n  屏幕坐标 (CSS): ({coords['css']['x']}, {coords['css']['y']})")
            print(f"  屏幕坐标 (物理): ({coords['physical']['x']}, {coords['physical']['y']})")
            print(f"  尺寸: {coords['width']}x{coords['height']}")
        except Exception as e:
            print(f"\n  坐标查询失败: {e}")

        print(f"\n{'=' * 60}")
        print("完整 JSON")
        print(f"{'=' * 60}")
        print(json.dumps({"jobs": jobs, "tab": tab_info}, ensure_ascii=False, indent=2))

    except asyncio.TimeoutError:
        log.error("超时")
    except Exception as e:
        log.error("出错: %s", e)
        import traceback; traceback.print_exc()
    finally:
        server_task.cancel()
        try: await server_task
        except: pass


if __name__ == "__main__":
    asyncio.run(main())

import { QueryFilter, BboxResult, QueryMeta, RawElement } from '../protocol/types';

interface QueryEngineArgs {
  select: string;
  filter?: QueryFilter;
  project?: Record<string, string | string[]>;
  return: 'bbox' | 'bboxList' | 'list' | 'first' | 'count' | 'raw';
}

interface QueryEngineResult {
  data: any;
  _meta?: QueryMeta;
  __error__?: string;
}

export function queryEngine(args: QueryEngineArgs): QueryEngineResult {
  function bboxOf(el: Element): BboxResult {
    const rect = el.getBoundingClientRect();
    const borderThickness = (window.outerWidth - window.innerWidth) / 2;
    const topUIHeight = window.outerHeight - window.innerHeight - borderThickness;
    const cssX = window.screenX + borderThickness + rect.left;
    const cssY = window.screenY + topUIHeight + rect.top;
    const dpr = window.devicePixelRatio || 1;
    return {
      css: {
        x: Math.round(cssX),
        y: Math.round(cssY),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
        cx: Math.round(cssX + rect.width / 2),
        cy: Math.round(cssY + rect.height / 2),
      },
      physical: {
        x: Math.round(cssX * dpr),
        y: Math.round(cssY * dpr),
        w: Math.round(rect.width * dpr),
        h: Math.round(rect.height * dpr),
        cx: Math.round((cssX + rect.width / 2) * dpr),
        cy: Math.round((cssY + rect.height / 2) * dpr),
      },
    };
  }

  function parseProjectSpec(spec: string): { sub: string; attr: string } {
    const atIdx = spec.lastIndexOf('@');
    if (atIdx === -1) return { sub: spec || '', attr: 'text' };
    return { sub: atIdx === 0 ? '' : spec.slice(0, atIdx), attr: spec.slice(atIdx + 1) };
  }

  function getAttr(el: Element, attr: string, all: Element[]): string | number {
    switch (attr) {
      case 'text':
        return (el.textContent || '').replace(/\s+/g, ' ').trim();
      case 'html':
        return el.innerHTML || '';
      case 'index':
        return all.indexOf(el);
      default:
        if (attr.startsWith('class~')) return (el as HTMLElement).classList.contains(attr.slice(6)) ? 'true' : 'false';
        return el.getAttribute(attr) || '';
    }
  }

  function applyFilter(all: Element[], filter?: QueryFilter): Element[] {
    if (!filter) return all;
    let result = all;
    if (filter.textContains) {
      const kw = String(filter.textContains);
      result = result.filter((el) => (el.textContent || '').includes(kw));
    }
    if (filter.textAny) {
      const kws = Array.isArray(filter.textAny) ? filter.textAny : [filter.textAny];
      result = result.filter((el) => {
        const text = el.textContent || '';
        return kws.some((kw) => text.includes(kw));
      });
    }
    if (filter.textNone) {
      const kws = Array.isArray(filter.textNone) ? filter.textNone : [filter.textNone];
      result = result.filter((el) => {
        const text = el.textContent || '';
        return !kws.some((kw) => text.includes(kw));
      });
    }
    if (filter.nth === 'last' && result.length > 0) {
      result = [result[result.length - 1]];
    }
    if (filter.index !== undefined) {
      const idx = parseInt(String(filter.index), 10);
      result = idx >= 0 && idx < result.length ? [result[idx]] : [];
    }
    return result;
  }

  function projectEl(el: Element, all: Element[], project?: Record<string, string | string[]>): Record<string, any> {
    if (!project) return {};
    const result: Record<string, any> = {};
    for (const key in project) {
      if (!project.hasOwnProperty(key)) continue;
      const spec = project[key];
      if (Array.isArray(spec)) {
        const values: any[] = [];
        for (const s of spec) {
          const parsed = parseProjectSpec(s);
          if (parsed.sub) {
            const subs = el.querySelectorAll(parsed.sub);
            subs.forEach((sub) => values.push(getAttr(sub, parsed.attr, all)));
          } else {
            values.push(getAttr(el, parsed.attr, all));
          }
        }
        result[key] = values;
      } else {
        const parsed = parseProjectSpec(spec);
        if (parsed.sub) {
          const subEl = el.querySelector(parsed.sub);
          result[key] = subEl ? getAttr(subEl, parsed.attr, all) : null;
        } else {
          result[key] = getAttr(el, parsed.attr, all);
        }
      }
    }
    return result;
  }

  try {
    const t0 = performance.now();
    const all = Array.from(document.querySelectorAll(args.select));
    const matched = applyFilter(all, args.filter);
    let data: any;

    switch (args.return) {
      case 'bbox':
        data = matched[0] ? (matched[0].scrollIntoView({ block: 'center', behavior: 'instant' }), bboxOf(matched[0])) : null;
        break;
      case 'bboxList':
        data = matched.map(bboxOf);
        break;
      case 'list':
        data = matched.map((el) => projectEl(el, all, args.project));
        break;
      case 'first':
        data = matched[0] ? projectEl(matched[0], all, args.project) : null;
        break;
      case 'count':
        data = matched.length;
        break;
      case 'raw':
        data = matched.map((el): RawElement => ({
          text: (el.textContent || '').trim(),
          html: el.outerHTML,
        }));
        break;
      default:
        throw new Error('unknown return: ' + args.return);
    }

    return {
      data,
      _meta: {
        url: location.href,
        matched: matched.length,
        tookMs: Math.round(performance.now() - t0),
      },
    };
  } catch (e) {
    return { data: null, _meta: undefined, __error__: String(e) };
  }
}

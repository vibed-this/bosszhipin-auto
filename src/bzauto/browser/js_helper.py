"""注入到每个 QWebEnginePage 的 JS_HELPER 字符串 — 挂到 window.__bz。"""

JS_HELPER = r"""
(function() {
if (window.__bz) return;
window.__bz = {};

function parseProjectSpec(spec) {
  var atIdx = spec.lastIndexOf('@');
  if (atIdx === -1) return { sub: spec || '', attr: 'text' };
  return { sub: atIdx === 0 ? '' : spec.slice(0, atIdx), attr: spec.slice(atIdx + 1) };
}

function getAttr(el, attr, all) {
  switch (attr) {
    case 'text': return (el.textContent || '').replace(/\s+/g, ' ').trim();
    case 'html': return el.innerHTML || '';
    case 'index': return all.indexOf(el);
    default:
      if (attr.startsWith('class~')) return el.classList.contains(attr.slice(6)) ? 'true' : 'false';
      return el.getAttribute(attr) || '';
  }
}

function applyFilter(all, filter) {
  if (!filter) return all;
  var result = all;
  if (filter.textContains) {
    var kw = String(filter.textContains);
    result = result.filter(function(el) { return (el.textContent || '').includes(kw); });
  }
  if (filter.textAny) {
    var kws = Array.isArray(filter.textAny) ? filter.textAny : [filter.textAny];
    result = result.filter(function(el) {
      var text = el.textContent || '';
      return kws.some(function(kw) { return text.includes(kw); });
    });
  }
  if (filter.textNone) {
    var kws = Array.isArray(filter.textNone) ? filter.textNone : [filter.textNone];
    result = result.filter(function(el) {
      var text = el.textContent || '';
      return !kws.some(function(kw) { return text.includes(kw); });
    });
  }
  if (filter.nth === 'last' && result.length > 0) {
    result = [result[result.length - 1]];
  }
  if (filter.index !== undefined) {
    var idx = parseInt(String(filter.index), 10);
    result = idx >= 0 && idx < result.length ? [result[idx]] : [];
  }
  return result;
}

function projectEl(el, all, project) {
  if (!project) return {};
  var result = {};
  for (var key in project) {
    if (!project.hasOwnProperty(key)) continue;
    var spec = project[key];
    if (Array.isArray(spec)) {
      var values = [];
      for (var si = 0; si < spec.length; si++) {
        var parsed = parseProjectSpec(spec[si]);
        if (parsed.sub) {
          var subs = el.querySelectorAll(parsed.sub);
          for (var si2 = 0; si2 < subs.length; si2++) values.push(getAttr(subs[si2], parsed.attr, all));
        } else {
          values.push(getAttr(el, parsed.attr, all));
        }
      }
      result[key] = values;
    } else {
      var parsed = parseProjectSpec(spec);
      if (parsed.sub) {
        var subEl = el.querySelector(parsed.sub);
        result[key] = subEl ? getAttr(subEl, parsed.attr, all) : null;
      } else {
        result[key] = getAttr(el, parsed.attr, all);
      }
    }
  }
  return result;
}

window.__bz.bboxOf = function(select, filter) {
  var all = Array.from(document.querySelectorAll(select));
  var matched = applyFilter(all, filter || {});
  if (matched.length === 0) return null;
  var el = matched[0];
  el.scrollIntoView({ block: 'center', behavior: 'instant' });
  var rect = el.getBoundingClientRect();
  return { x: rect.x, y: rect.y, w: rect.width, h: rect.height, cx: Math.round(rect.x + rect.width / 2), cy: Math.round(rect.y + rect.height / 2) };
};

window.__bz.findAll = function(select, filter, project) {
  var all = Array.from(document.querySelectorAll(select));
  var matched = applyFilter(all, filter || {});
  return matched.map(function(el) { return projectEl(el, all, project || {}); });
};

window.__bz.findOne = function(select, filter, project) {
  var all = Array.from(document.querySelectorAll(select));
  var matched = applyFilter(all, filter || {});
  if (matched.length === 0) return null;
  return projectEl(matched[0], all, project || {});
};

window.__bz.count = function(select, filter) {
  var all = Array.from(document.querySelectorAll(select));
  return applyFilter(all, filter || {}).length;
};

window.__bz.dumpHtml = function() {
  return document.documentElement ? document.documentElement.outerHTML : null;
};
})();
"""

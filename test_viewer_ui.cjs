// Run with: npm ci && npm test
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const { webcrypto: crypto } = require('node:crypto');
const { JSDOM } = require('jsdom');
const marked = require('./vendor/marked.umd.js');
const DOMPurify = require('./vendor/purify.min.js')(new JSDOM('').window);
const html = readFileSync(`${__dirname}/viewer.html`, 'utf8');
const functions = html.slice(html.indexOf('  function canPost()'), html.indexOf('  function setComposerBusy('));

for (const state of [
  { name: 'initialization pending', ready: false, source: 'notes', folder: '音楽', busy: false, saveDisabled: true },
  { name: 'no folder selected', ready: true, source: 'notes', folder: '', busy: false, saveDisabled: true },
  { name: 'selected folder', ready: true, source: 'notes', folder: '音楽', busy: false, saveDisabled: false },
  { name: 'archive draft', ready: true, source: 'archive', folder: '', busy: false, saveDisabled: true },
  { name: 'saving', ready: true, source: 'notes', folder: '音楽', busy: true, saveDisabled: true },
]) {
  test(`composer: ${state.name}`, () => {
    const elements = {
      'post-target': {},
      'post-text': { disabled: false, value: '下書き' },
      'post-save': { disabled: false },
      'post-image': { disabled: false },
    };
    const context = {
      composerReady: state.ready, composerBusy: state.busy,
      currentSource: state.source, currentFolder: state.folder,
      document: {
        getElementById: id => elements[id],
        querySelectorAll: selector => selector.includes('textarea')
          ? [elements['post-text'], elements['post-save'], elements['post-image']]
          : [elements['post-save'], elements['post-image']],
      },
    };
    vm.runInNewContext(`${functions}\nupdateComposer();`, context);
    assert.equal(elements['post-text'].disabled, state.busy, 'typing is blocked only while saving/uploading');
    assert.equal(elements['post-save'].disabled, state.saveDisabled);
    assert.equal(elements['post-text'].value, '下書き');
  });
}

const rendering = html.slice(html.indexOf('  function escapeHtml('), html.indexOf('  function formatDatetime('));
function renderText(text) {
  const context = { text };
  vm.runInNewContext(`${rendering}\nresult = renderContent(text);`, context);
  return context.result;
}

test('URL thumbnail belongs to link block exactly once', () => {
  const result = renderText('https://example.com  \ntitle: Example  \ndescription: Text  \n![](../assets/thumb.webp)  \n');
  assert.match(result, /<div class="url-block">[\s\S]*<img[\s\S]*?thumb.webp[\s\S]*?><\/div><\/div>/);
  assert.equal((result.match(/<img /g) || []).length, 1);
});

test('blank line keeps independent image outside the link block', () => {
  const result = renderText('https://example.com\ntitle: Example\n\n![](../assets/photo.webp)');
  assert.match(result, /<\/a><\/div><div class="line-empty"><\/div><div class="line-image">/);
});

function renderArticles(dates, source = 'inbox') {
  const elements = new Map();
  const context = {
    filtered: () => dates.map((created_at, i) => ({ id: String(i), created_at, content: '', tags: [] })),
    renderSearchResults() {},
    updateSidebarCounts() {},
    editDrafts: new Map(), expandedArticles: new Set(), scopeQuery: () => 'source=inbox',
    updateTagButtonAvailability() {}, activeTags: new Set(), dateFrom: '', dateTo: '', currentSource: source,
    document: { getElementById(id) {
      if (!elements.has(id)) elements.set(id, { style: {}, classList: { toggle() {} }, setAttribute() {} });
      return elements.get(id);
    } },
  };
  const code = html.slice(html.indexOf('  function escapeHtml('), html.indexOf('  // --- 記事内編集 ---'));
  vm.runInNewContext(`${code}\nrender();`, context);
  return elements.get('cards').innerHTML;
}

test('date separator appears only at a change of day', () => {
  const result = renderArticles(['2026-09-22T10:00:00', '2026-09-22T09:00:00', '2026-09-21T23:59:00', '2026-09-21T08:00:00']);
  assert.equal((result.match(/class="date-separator"/g) || []).length, 1);
  assert.match(result, /class="date-separator"><span>2026\/09\/21<\/span>/);
});

test('single day or empty list has no date separator', () => {
  for (const dates of [[], ['2026-09-22T10:00:00'], ['2026-09-22T10:00:00', '2026-09-22T09:00:00']]) {
    assert.doesNotMatch(renderArticles(dates), /class="date-separator"/);
  }
});

test('articles display oldest first without changing source data', () => {
  const allFragments = [
    { id: 'new', created_at: '2026-09-22T12:00:00' },
    { id: 'old', created_at: '2026-09-21T12:00:00' },
    { id: 'middle', created_at: '2026-09-22T10:00:00' },
  ];
  const code = html.slice(html.indexOf('  function filtered('), html.indexOf('  function updateTagButtonAvailability()'));
  const context = { allFragments, matchesFilters: () => true, activeTags: new Set() };
  vm.runInNewContext(`${code}\nresult = filtered();`, context);
  assert.deepEqual(Array.from(context.result, f => f.id), ['old', 'middle', 'new']);
  assert.deepEqual(allFragments.map(f => f.id), ['new', 'old', 'middle']);
});

const filtering = html.slice(html.indexOf('  function matchesFilters('), html.indexOf('  function updateTagButtonAvailability()'));
function filterArticles(fragments, { activeTags = new Set(), searchQuery = '', dateFrom = '', dateTo = '', showFavoritesOnly = false, tagMode = 'AND' } = {}, expression = 'filtered()') {
  const context = { allFragments: fragments, activeTags, searchQuery, dateFrom, dateTo, showFavoritesOnly, tagMode };
  vm.runInNewContext(`${filtering}\nresult = ${expression};`, context);
  return context.result;
}

test('search and date filters apply only when filtering search results', () => {
  const fragments = [
    { id: 'match', content: 'needle', created_at: '2026-09-22T12:00:00', tags: [] },
    { id: 'query-miss', content: 'haystack', created_at: '2026-09-22T12:00:00', tags: [] },
    { id: 'date-miss', content: 'needle', created_at: '2026-09-21T12:00:00', tags: [] },
  ];
  const filters = { searchQuery: 'needle', dateFrom: '2026-09-22', dateTo: '2026-09-22' };
  assert.deepEqual(filterArticles(fragments, filters).map(f => f.id), ['date-miss', 'match', 'query-miss']);
  assert.deepEqual(filterArticles(fragments, filters, 'filtered(true)').map(f => f.id), ['match']);
});

test('search filtering still shares selected tags and favorite-only state', () => {
  const fragments = [
    { id: 'tagged-favorite', content: 'needle', created_at: '2026-09-22T12:00:00', tags: ['music', 'favorite'] },
    { id: 'tagged', content: 'needle', created_at: '2026-09-22T12:00:00', tags: ['music'] },
    { id: 'other-tag', content: 'needle', created_at: '2026-09-22T12:00:00', tags: ['movie', 'favorite'] },
  ];
  const filters = { activeTags: new Set(['music']), searchQuery: 'needle', showFavoritesOnly: true };
  assert.deepEqual(filterArticles(fragments, filters, 'filtered(true)').map(f => f.id), ['tagged-favorite']);
  assert.equal(filterArticles(fragments, filters, 'matchesFilters(allFragments[0], new Set(["music", "missing"]), true)'), false);
});

test('search query and dates do not disable sidebar tag candidates', () => {
  const fragments = [
    { id: 'candidate', content: 'unrelated', created_at: '2026-09-21T12:00:00', tags: ['music'] },
    { id: 'search-match', content: 'needle', created_at: '2026-09-22T12:00:00', tags: [] },
  ];
  const button = { dataset: { tag: 'music' }, disabled: false, title: '' };
  const context = {
    allFragments: fragments, activeTags: new Set(), searchQuery: 'needle',
    dateFrom: '2026-09-22', dateTo: '2026-09-22', showFavoritesOnly: false, tagMode: 'AND',
    document: { querySelectorAll: () => [button] },
  };
  const availability = html.slice(html.indexOf('  function updateTagButtonAvailability()'), html.indexOf('  // --- コンテンツ描画 ---'));
  vm.runInNewContext(`${filtering}\n${availability}\nupdateTagButtonAvailability();`, context);
  assert.equal(button.disabled, false);
  assert.equal(button.title, '');
});

test('end date includes fractional seconds through the last second', () => {
  const fragments = [
    { id: 'last-whole-second', content: '', created_at: '2026-09-22T23:59:59', tags: [] },
    { id: 'fractional', content: '', created_at: '2026-09-22T23:59:59.999999', tags: [] },
    { id: 'next-day', content: '', created_at: '2026-09-23T00:00:00', tags: [] },
  ];
  assert.deepEqual(filterArticles(fragments, { dateTo: '2026-09-22' }, 'filtered(true)').map(f => f.id), ['last-whole-second', 'fractional']);
});

function searchPanelContext(mobile = false) {
  const dom = new JSDOM(html);
  const { document } = dom.window;
  const mainCard = document.createElement('article');
  mainCard.className = 'card';
  mainCard.dataset.id = 'main-card';
  document.getElementById('cards').append(mainCard);
  const fragments = [
    { id: 'needle-old', content: 'needle older', created_at: '2026-09-21T12:00:00', tags: [] },
    { id: 'needle-new', content: 'needle newer', created_at: '2026-09-22T12:00:00', tags: [] },
    { id: 'other-new', content: 'other', created_at: '2026-09-22T13:00:00', tags: [] },
  ];
  const media = { matches: mobile, addEventListener() {} };
  const context = {
    document,
    window: { matchMedia: () => media },
    allFragments: fragments, activeTags: new Set(), searchQuery: '', dateFrom: '', dateTo: '',
    showFavoritesOnly: false, tagMode: 'AND', currentFolder: '', currentSource: 'inbox',
    searchExpandedArticles: new Set(), displayedScrollKey: 'inbox', restoringScroll: null,
    viewerScroll: document.getElementById('viewer-scroll'), lightbox: document.getElementById('lightbox'),
    visibleArticleTop: () => 0, applyScrollPosition() {},
    escapeHtml: value => String(value), formatDatetime: value => value,
    renderArticleBody: fragment => fragment.content,
  };
  const filteringCode = html.slice(html.indexOf('  function matchesFilters('), html.indexOf('  function updateTagButtonAvailability()'));
  const panelCode = html.slice(html.indexOf('  // --- 右カラムの検索 ---'), html.indexOf('  document.getElementById("tag-clear-btn").addEventListener("click"'));
  const showErrorCode = html.slice(html.indexOf('  function showError('), html.indexOf('  async function request('));
  vm.createContext(context);
  vm.runInContext(`${showErrorCode}\n${filteringCode}\n${panelCode}`, context);
  return { dom, context, mainCard, media };
}

test('search panel keeps the main feed and scroll intact, scopes dates, and restores focus on close', () => {
  const { dom, context, mainCard } = searchPanelContext();
  const { document } = dom.window;
  const scroll = document.getElementById('viewer-scroll');
  scroll.scrollTop = 321;
  const toggle = document.getElementById('search-toggle');
  toggle.click();
  assert.equal(document.getElementById('search-panel').hidden, false);
  assert.equal(document.activeElement.id, 'search');

  const search = document.getElementById('search');
  search.value = 'needle';
  search.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  const dateFrom = document.getElementById('date-from');
  dateFrom.value = '2026-09-22';
  dateFrom.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  const dateTo = document.getElementById('date-to');
  dateTo.value = '2026-09-22';
  dateTo.dispatchEvent(new dom.window.Event('change', { bubbles: true }));

  assert.equal(context.dateTo, '2026-09-22');
  assert.deepEqual(Array.from(context.filtered(true), fragment => fragment.id), ['needle-new']);
  assert.deepEqual([...document.querySelectorAll('#search-cards .card')].map(card => card.dataset.id), ['needle-new']);
  assert.equal(document.querySelector('#cards .card'), mainCard);
  assert.equal(scroll.scrollTop, 321);
  assert.equal(context.searchQuery, 'needle');
  context.showError(new Error('検索に失敗しました'));
  assert.equal(document.getElementById('search-status').hidden, false);
  assert.equal(document.getElementById('search-status').textContent, '検索に失敗しました');

  document.getElementById('search-close').click();
  assert.equal(document.getElementById('search-panel').hidden, true);
  assert.equal(document.activeElement, toggle);
  assert.equal(search.value, '');
  assert.equal(dateFrom.value, '');
  assert.equal(dateTo.value, '');
  assert.equal(document.getElementById('search-cards').children.length, 0);
  assert.equal(context.searchQuery, '');
  assert.equal(context.dateTo, '');
  assert.equal(document.getElementById('search-status').hidden, true);
  assert.equal(document.querySelector('#cards .card'), mainCard);
  assert.equal(scroll.scrollTop, 321);
  dom.window.close();
});

test('mobile search makes the main feed and folder sidebar inert until closed', () => {
  const { dom } = searchPanelContext(true);
  const { document } = dom.window;
  document.getElementById('search-toggle').click();
  assert.equal(document.querySelector('main').inert, true);
  assert.equal(document.getElementById('folder-pane').inert, true);
  document.getElementById('search-back').click();
  assert.equal(document.querySelector('main').inert, false);
  assert.equal(document.getElementById('folder-pane').inert, false);
  dom.window.close();
});

test('expanding a search result uses separate expansion state and leaves the main scroll alone', () => {
  const fragment = { id: 'long-search', content: '😀'.repeat(2000) + '末尾', tag_lines: [] };
  const dom = new JSDOM('<div id="cards"><div class="card"><div class="card-body"></div></div></div><div id="search-cards"><div class="card"><div class="card-body"></div></div></div>');
  const { document } = dom.window;
  const mainCard = document.querySelector('#cards .card');
  const searchCard = document.querySelector('#search-cards .card');
  const viewerScroll = { scrollTop: 321 };
  document.getElementById('search-scroll')?.remove();
  const searchScrollElement = document.createElement('div');
  searchScrollElement.id = 'search-scroll';
  searchScrollElement.getBoundingClientRect = () => ({ top: 0 });
  document.body.append(searchScrollElement);
  const context = {
    document, fragment, allFragments: [fragment], editDrafts: new Map(),
    expandedArticles: new Set(), searchExpandedArticles: new Set(), scopeQuery: () => 'inbox',
    viewerScroll, visibleArticleTop: () => 80, restoringScroll: null, crypto, marked, DOMPurify,
    mainCard, searchCard,
  };
  vm.createContext(context);
  vm.runInContext(`${rendering}\nmainCard.querySelector('.card-body').innerHTML = renderArticleBody(fragment); searchCard.querySelector('.card-body').innerHTML = renderArticleBody(fragment, true); toggleArticleExpansion(searchCard.querySelector('button'));`, context);
  assert.equal(searchCard.querySelector('button').getAttribute('aria-expanded'), 'true');
  assert.equal(context.searchExpandedArticles.has(JSON.stringify(['inbox', 'long-search'])), true);
  assert.equal(context.expandedArticles.size, 0);
  assert.equal(viewerScroll.scrollTop, 321);
  assert.doesNotMatch(mainCard.querySelector('.card-body').innerHTML, /末尾/);
  dom.window.close();
});

test('inline viewer script parses', () => {
  const start = html.indexOf('<script>', html.indexOf('</aside>')) + '<script>'.length;
  const end = html.indexOf('</script>', start);
  assert.ok(start >= '<script>'.length && end > start);
  assert.doesNotThrow(() => new vm.Script(html.slice(start, end)));
});

test('folder scroll positions restore independently and new folders start at bottom', () => {
  const listeners = {};
  const scroll = {
    scrollHeight: 1200, clientHeight: 300, top: 0,
    get scrollTop() { return this.top; },
    set scrollTop(value) { this.top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight)); },
    addEventListener(name, callback) { listeners[name] = callback; },
  };
  const context = {
    document: { getElementById: () => scroll },
    ResizeObserver: class { observe() {} },
  };
  const code = html.slice(html.indexOf('  const folderScrollPositions'), html.indexOf('  // --- データ取得 ---'));
  vm.createContext(context);
  vm.runInContext(code, context);
  const run = code => vm.runInContext(code, context);
  run('restoreScrollPosition("A")');
  assert.equal(scroll.scrollTop, 900);
  listeners.wheel();
  scroll.scrollTop = 240;
  run('rememberScrollPosition(); restoreScrollPosition("B")');
  assert.equal(scroll.scrollTop, 900);
  run('rememberScrollPosition(); restoreScrollPosition("A")');
  assert.equal(scroll.scrollTop, 240);
  run('rememberScrollPosition(); restoreScrollPosition("B")');
  scroll.scrollHeight = 1600;
  run('applyScrollPosition()');
  assert.equal(scroll.scrollTop, 1300, 'bottom follows delayed image layout');
  listeners.wheel();
  scroll.scrollTop = 0;
  run('applyScrollPosition()');
  assert.equal(scroll.scrollTop, 0, 'user scroll is not overridden');
  run('rememberScrollPosition(); restoreScrollPosition("B")');
  assert.equal(scroll.scrollTop, 0, 'zero is a remembered position');
  run('rememberScrollPosition(); rememberScrollPosition(); restoreScrollPosition("B")');
  assert.equal(scroll.scrollTop, 0, 'loading state does not overwrite the saved position');
});

test('inline editor escapes text and scopes drafts by folder', () => {
  const editDrafts = new Map();
  const context = { crypto, marked, DOMPurify, expandedArticles: new Set(), editDrafts, scopeQuery: () => 'folder=A', fragment: { id: '1', content: 'original' } };
  const code = html.slice(html.indexOf('  function escapeHtml('), html.indexOf('  function formatDatetime('));
  vm.createContext(context);
  vm.runInContext(code, context);
  vm.runInContext('editDrafts.set(editKey("1"), {content: "</textarea><script>bad</script>", busy: false}); result = renderArticleBody(fragment);', context);
  assert.match(context.result, /class="edit-textarea"/);
  assert.ok(context.result.includes('&lt;/textarea&gt;&lt;script&gt;'));
  context.scopeQuery = () => 'folder=B';
  vm.runInContext('result = renderArticleBody(fragment)', context);
  assert.doesNotMatch(context.result, /edit-textarea/);
});

for (const fails of [false, true]) {
  test(`inline save ${fails ? 'retains draft on failure' : 'updates article and closes editor'}`, async () => {
    const key = JSON.stringify(['folder=A', '1']);
    const drafts = new Map([[key, { content: 'edited', busy: false }]]);
    const context = {
      editDrafts: drafts, editKey: () => key, scopeQuery: () => 'folder=A',
      allFragments: [{ id: '1', content: 'original' }], render() {},
      async request(url, options) {
        assert.equal(JSON.parse(options.body).content, 'edited');
        if (fails) throw new Error('save failed');
        return { id: '1', content: 'edited' };
      },
    };
    const code = html.slice(html.indexOf('  async function saveEdit('), html.indexOf('  document.getElementById("cards").addEventListener("input"'));
    await vm.runInNewContext(`${code}\nsaveEdit("1");`, context);
    if (fails) {
      assert.equal(drafts.get(key).content, 'edited');
      assert.equal(drafts.get(key).busy, false);
      assert.equal(drafts.get(key).error, 'save failed');
      assert.equal(context.allFragments[0].content, 'original');
    } else {
      assert.equal(drafts.size, 0);
      assert.equal(context.allFragments[0].content, 'edited');
    }
  });
}

test('inline link metadata stays in a removable card outside textareas', () => {
  const content = 'before\nhttps://example.com  \ntitle: Example  \ndescription: Details  \n![](../assets/thumb.webp)  \nafter';
  const context = { editDrafts: new Map(), expandedArticles: new Set(), scopeQuery: () => 'A', fragment: { id: '1', content } };
  const code = html.slice(html.indexOf('  function escapeHtml('), html.indexOf('  function formatDatetime('));
  vm.createContext(context);
  vm.runInContext(code, context);
  vm.runInContext('editDrafts.set(editKey("1"), {content: fragment.content}); result = renderArticleBody(fragment);', context);
  assert.match(context.result, /class="edit-remove-link"/);
  assert.match(context.result, /class="url-block"/);
  const textareas = [...context.result.matchAll(/<textarea[^>]*>([\s\S]*?)<\/textarea>/g)].map(m => m[1]).join('');
  assert.doesNotMatch(textareas, /title:|description:|thumb.webp|https:\/\/example/);
  vm.runInContext('const draft = editDrafts.get(editKey("1")); draft.parts = draft.parts.filter(p => p.type !== "link"); result = serializeEditParts(draft.parts);', context);
  assert.equal(context.result, 'before\nafter');
});

test('folder selection survives reload in session storage only', () => {
  const code = html.slice(html.indexOf('  function readFolderSelection('), html.indexOf('  function canPost('));
  const saved = new Map();
  const sessionStorage = { getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value) };
  for (const [source, folder] of [['notes', '音楽 & 映像'], ['inbox', ''], ['archive', 'Music']]) {
    vm.runInNewContext(code + '\nrememberFolderSelection();', { sessionStorage, currentSource: source, currentFolder: folder });
    const reloaded = { sessionStorage };
    vm.runInNewContext(code + '\nselection = readFolderSelection();', reloaded);
    assert.equal(reloaded.selection.source, source);
    assert.equal(reloaded.selection.folder, folder);
  }
  const fresh = { sessionStorage: { getItem: () => null } };
  vm.runInNewContext(code + '\nselection = readFolderSelection();', fresh);
  assert.equal(fresh.selection.source, 'inbox');
});

test('corrected image shows original and correct paths; missing image is reported', () => {
  const code = html.slice(html.indexOf('  function escapeHtml('), html.indexOf('  function formatDatetime('));
  const context = {};
  vm.createContext(context);
  vm.runInContext(code, context);
  vm.runInContext(`result = renderLine('![](../assets/a.webp)', [{ original: '../assets/a.webp', status: 'corrected', corrected: '../../assets/a.webp', url: '/assets/a.webp' }]);`, context);
  assert.match(context.result, /リンク補正あり/);
  assert.match(context.result, /正しい参照: ..\/..\/assets\/a.webp/);
  vm.runInContext(`result = renderLine('![](../assets/a.webp)', [{ original: '../assets/a.webp', status: 'missing' }]);`, context);
  assert.match(context.result, /画像が見つかりません/);
  assert.doesNotMatch(context.result, /<img/);
  vm.runInContext(`result = renderLine('![](../../assets/a.webp)', [{ original: '../../assets/a.webp', status: 'ok', url: '/assets/a.webp' }]);`, context);
  assert.doesNotMatch(context.result, /リンク補正あり/);
});

test('fix button appears next to the image correction notice only outside editing', () => {
  const code = html.slice(html.indexOf('  function escapeHtml('), html.indexOf('  function formatDatetime('));
  const context = { links: [{ original: '../assets/a.webp', status: 'corrected', corrected: '../../assets/a.webp', url: '/assets/a.webp' }] };
  vm.createContext(context);
  vm.runInContext(code + `\nresult = renderContent('![](../assets/a.webp)', links, 'note');`, context);
  assert.match(context.result, /class="image-link-notice">[\s\S]*<\/details><button class="repair-images-btn"[^>]*>fix<\/button><\/div>/);
  vm.runInContext(`result = renderContent('![](../assets/a.webp)', links);`, context);
  assert.doesNotMatch(context.result, /repair-images-btn/);
});


test('archive button is shown only on active articles', () => {
  assert.match(renderArticles(['2026-09-22T12:00:00']), /class="archive-btn"/);
  assert.doesNotMatch(renderArticles(['2026-09-22T12:00:00'], 'archive'), /class="archive-btn"/);
});

test('restore button is shown only on archived articles', () => {
  assert.doesNotMatch(renderArticles(['2026-09-22T12:00:00']), /class="restore-btn"/);
  assert.match(renderArticles(['2026-09-22T12:00:00'], 'archive'), /class="restore-btn"[^>]*aria-label="元のフォルダに戻す"/);
});


test('move button excludes archived articles and folder search preserves order', () => {
  assert.match(renderArticles(['2026-09-22T12:00:00']), /class="move-btn"/);
  assert.doesNotMatch(renderArticles(['2026-09-22T12:00:00'], 'archive'), /class="move-btn"/);
  const code = html.slice(html.indexOf('  function moveCandidates('), html.indexOf('  function openMovePicker('));
  const context = {};
  vm.createContext(context);
  vm.runInContext(code, context);
  const entries = [
    { source: 'notes', folder: 'Music', name: 'Music' },
    { source: 'inbox', folder: '', name: 'inbox' },
    { source: 'notes', folder: '音楽', name: '音楽' },
    { source: 'archive', folder: 'Music', name: 'Music' },
  ];
  assert.equal(context.moveCandidates(entries, 'notes', 'Music', '').map(e => e.name).join(','), 'inbox,音楽');
  assert.equal(context.moveCandidates(entries, 'inbox', '', '  MUSIC ').map(e => e.name).join(','), 'Music');
  assert.equal(context.moveCandidates(entries, 'inbox', '', '音').map(e => e.name).join(','), '音楽');
  assert.equal(context.moveCandidates(entries, 'inbox', '', 'missing').length, 0);
});


test('multiple link thumbnails stay in one gallery and one editable link part', () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function escapeHtml('), html.indexOf('  function formatDatetime(')), context);
  const content = 'https://example.com\ntitle: Example\n![](../../assets/a.jpg)  \n![](../../assets/b.jpg)  \n\nAfter';
  context.content = content;
  vm.runInContext('result = renderContent(content);', context);
  assert.match(context.result, /class="link-thumbnails multiple"/);
  assert.equal((context.result.match(/class="link-thumbnail"/g) || []).length, 2);
  vm.runInContext(html.slice(html.indexOf('  function splitEditParts('), html.indexOf('  function renderArticleBody(')), context);
  vm.runInContext('parts = splitEditParts(content);', context);
  const link = context.parts.find(part => part.type === 'link');
  assert.match(link.raw, /a.jpg/);
  assert.match(link.raw, /b.jpg/);
  assert.doesNotMatch(link.raw, /After/);
});


test('folder rename retains selection, scroll positions and edit drafts', () => {
  const scope = (source, folder) => new URLSearchParams({ source, folder }).toString();
  const oldScope = scope('notes', 'Music');
  const archiveScope = scope('archive', 'Music');
  const context = {
    URLSearchParams, currentSource: 'notes', currentFolder: 'Music',
    rememberScrollPosition() {}, rememberFolderSelection() {}, activeTags: new Set(),
    folderScrollPositions: new Map([[oldScope, 120], [archiveScope, 240]]),
    editDrafts: new Map([[JSON.stringify([oldScope, 'a']), { content: 'draft' }]]),
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function changeFolderState('), html.indexOf('  function openFolderMenu(')), context);
  context.changeFolderState('Music', '音楽');
  assert.equal(context.currentFolder, '音楽');
  assert.equal(context.folderScrollPositions.get(scope('notes', '音楽')), 120);
  assert.equal(context.folderScrollPositions.get(scope('archive', '音楽')), 240);
  assert.equal(context.editDrafts.get(JSON.stringify([scope('notes', '音楽'), 'a'])).content, 'draft');
  context.changeFolderState('音楽', null);
  assert.equal(context.currentSource, 'inbox');
  assert.equal(context.currentFolder, '');
  assert.equal(context.editDrafts.size, 0);
  assert.equal(context.folderScrollPositions.get(scope('archive', '音楽')), 240);
});

test('edit tag completion uses folder tags and replaces the whole token', () => {
  const code = html.slice(html.indexOf('  function editTagCompletion('), html.indexOf('  let tagSuggestionState'));
  const context = {};
  vm.createContext(context);
  vm.runInContext(code, context);
  const fragments = [{ tags: ['music', 'm4l', '音楽'] }, { tags: ['music', 'movie'] }];
  const result = context.editTagCompletion('メモ #mu 後ろ', 6, 6, fragments);
  assert.equal(result.start, 3);
  assert.equal(result.end, 6);
  assert.equal(result.tags.join(','), 'music');
  assert.equal(context.editTagCompletion('#音', 2, 2, fragments).tags.join(','), '音楽');
  assert.equal(context.editTagCompletion('#', 1, 1, fragments).tags.length, 4);
  assert.equal(context.editTagCompletion('https://example.com/#mu', 23, 23, fragments), null);
  assert.equal(context.editTagCompletion('#mu', 0, 3, fragments), null);
  assert.equal(context.editTagCompletion('#music', 3, 3, fragments).end, 6);
});

test('composer tag keys accept candidates without consuming save or IME keys', () => {
  const input = { disabled: false };
  let accepted = 0, closed = 0;
  const context = {
    tagSuggestionState: { input, popup: { isConnected: true, querySelector: () => null }, completion: { tags: ['a', 'b'] }, index: 0 },
    selectTagSuggestion() { accepted++; }, closeTagSuggestions() { closed++; }, paintTagSuggestions() {},
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function handleTagSuggestionKey('), html.indexOf('  postText.addEventListener("input"')), context);
  function press(key, extra = {}) {
    let prevented = false;
    const handled = context.handleTagSuggestionKey({ key, target: input, preventDefault() { prevented = true; }, ...extra });
    return { handled, prevented };
  }
  assert.equal(press('ArrowDown').handled, true);
  assert.equal(context.tagSuggestionState.index, 1);
  assert.equal(press('Enter').prevented, true);
  assert.equal(accepted, 1);
  assert.equal(press('Enter', { ctrlKey: true }).prevented, false);
  assert.equal(press('Enter', { metaKey: true }).prevented, false);
  assert.equal(press('Enter', { isComposing: true }).prevented, false);
  assert.equal(accepted, 1);
  assert.equal(press('Escape').handled, true);
  assert.equal(closed, 1);
});

test('tag filter redraw keeps the visible article at the same offset', () => {
  const scroll = { scrollTop: 300, getBoundingClientRect: () => ({ top: 100, bottom: 900 }) };
  let newLayout = false;
  const card = { dataset: { id: 'note' }, getBoundingClientRect: () => ({ top: newLayout ? 800 : 80, bottom: newLayout ? 1000 : 280 }) };
  const context = {
    viewerScroll: scroll, visibleArticleTop: () => 100, document: { querySelectorAll: () => [card] },
    filtered: () => [{ id: 'note' }], render() { newLayout = true; },
    displayedScrollKey: 'folder=A', restoringScroll: null,
    applyScrollPosition() { scroll.scrollTop += card.getBoundingClientRect().top - 100 - context.restoringScroll.anchor.offset; },
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function renderTagChange('), html.indexOf('  // --- タグフィルターボタン ---')), context);
  context.renderTagChange();
  assert.equal(scroll.scrollTop, 1020);
  assert.equal(context.restoringScroll.anchor.id, 'note');
  assert.equal(context.restoringScroll.anchor.offset, -20);
});


test('tag anchor ignores articles obscured by the sticky header', () => {
  const scroll = { scrollTop: 300, getBoundingClientRect: () => ({ top: 0, bottom: 600 }) };
  const hidden = { dataset: { id: 'hidden' }, getBoundingClientRect: () => ({ top: -30, bottom: 90 }) };
  const visible = { dataset: { id: 'visible' }, getBoundingClientRect: () => ({ top: 90, bottom: 300 }) };
  const context = {
    viewerScroll: scroll,
    document: { querySelector: () => ({ getBoundingClientRect: () => ({ bottom: 120 }) }), querySelectorAll: () => [hidden, visible] },
    filtered: () => [{ id: 'hidden' }, { id: 'visible' }], render() {}, applyScrollPosition() {},
    displayedScrollKey: 'folder=A', restoringScroll: null,
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function visibleArticleTop('), html.indexOf('  // --- タグフィルターボタン ---')), context);
  context.renderTagChange();
  assert.equal(context.restoringScroll.anchor.id, 'visible');
  assert.equal(context.restoringScroll.anchor.offset, -30);
});


test('tag controls and list live in the sidebar independently of article scrolling', () => {
  const sidebar = html.slice(html.indexOf('<aside'), html.indexOf('</aside>'));
  for (const id of ['tag-section', 'tag-filters', 'tag-search', 'tag-mode-btn', 'tag-clear-btn']) {
    assert.ok(sidebar.includes(`id="${id}"`));
  }
  assert.doesNotMatch(html, /tag-filter-slot|resetFloatingTags|tagScrollState|is-floating/);
});

test('article move archive and delete actions are inside a closed overflow menu', () => {
  const result = renderArticles(['2026-09-22T12:00:00']);
  assert.match(result, /class="article-menu-btn"[^>]*aria-expanded="false"/);
  const menu = result.match(/<div class="article-menu" role="menu" hidden>([\s\S]*?)<\/div>/)[1];
  for (const action of ['move-btn', 'archive-btn', 'delete-btn']) assert.match(menu, new RegExp(`class="${action}"`));
  assert.doesNotMatch(menu, /fav-btn|edit-btn/);
  assert.doesNotMatch(renderArticles(['2026-09-22T12:00:00'], 'archive'), /article-menu-btn/);
});


test('tag list search supports partial matching and keeps selected tags visible', () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function tagMatchesSearch('), html.indexOf('  function applyTagSearch(')), context);
  assert.equal(context.tagMatchesSearch('Music', ' #usi ', false), true);
  assert.equal(context.tagMatchesSearch('音楽制作', '制作', false), true);
  assert.equal(context.tagMatchesSearch('movie', 'music', false), false);
  assert.equal(context.tagMatchesSearch('movie', 'music', true), true);
  assert.equal(context.tagMatchesSearch('movie', '', false), true);
});


test('entering edit preserves the viewport and focuses without scrolling', () => {
  let restored = 0;
  let focusOptions;
  const context = {
    editKey: id => id, editDrafts: new Map(),
    renderTagChange() { restored++; },
    document: { querySelectorAll: () => [{ dataset: { id: 'a' }, querySelector: () => ({ focus(options) { focusOptions = options; } }) }] },
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function showEdit('), html.indexOf('  function editTagCompletion(')), context);
  context.showEdit('a', 'content');
  assert.equal(restored, 1);
  assert.equal(focusOptions.preventScroll, true);
  assert.equal(context.editDrafts.get('a').content, 'content');
});

test('geo tags form a final separate row and disappear when no search matches', () => {
  function node() {
    return {
      children: [], dataset: {}, classList: { toggle() {} }, hidden: false,
      appendChild(child) { this.children.push(child); }, addEventListener() {},
      querySelectorAll(selector) { return this.children.flatMap(child => [child, ...child.querySelectorAll(selector)]).filter(child => child.className === 'tag-btn'); },
    };
  }
  const container = node();
  const search = { value: '' };
  const context = {
    activeTags: new Set(),
    allFragments: [],
    document: {
      createElement: node,
      getElementById: id => id === 'tag-search' ? search : container,
      querySelectorAll: () => container.querySelectorAll('.tag-btn'),
      querySelector: () => container.children.find(child => child.className === 'geo-tag-group'),
    },
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function renderTagFilters('), html.indexOf('  document.getElementById("tag-search").addEventListener')), context);
  context.renderTagFilters(['geo_tokyo', 'music', 'geo_osaka', 'my_geo_tag']);
  assert.equal(container.children.slice(0, -1).map(child => child.dataset.tag).join(','), 'music,my_geo_tag');
  const group = container.children.at(-1);
  assert.equal(group.className, 'geo-tag-group');
  assert.equal(group.children.map(child => child.dataset.tag).join(','), 'geo_tokyo,geo_osaka');
  search.value = 'music';
  context.applyTagSearch();
  assert.equal(group.hidden, true);
  search.value = 'tokyo';
  context.applyTagSearch();
  assert.equal(group.hidden, false);
  assert.equal(group.children[0].hidden, false);
  assert.equal(group.children[1].hidden, true);
});

test('attachment cards escape names, display sizes and distinguish file kinds', () => {
  for (const [ext, kind] of [['pdf', 'pdf'], ['wav', 'audio'], ['mid', 'midi'], ['txt', 'text']]) {
    const asset = `attachment_${'a'.repeat(32)}.${ext}`;
    const content = `[name](../assets/${asset})  `;
    const attachments = [{ asset, name: '<script>[資料].' + ext, size: 16661872 }];
    const context = { content, attachments };
    vm.runInNewContext(`${rendering}\nresult = renderContent(content, [], null, attachments);`, context);
    assert.match(context.result, new RegExp(`attachment-${kind}`));
    assert.match(context.result, /15.89 MB/);
    assert.match(context.result, /class="attachment-download"/);
    assert.ok(context.result.includes(`download="&lt;script&gt;[資料].${ext}"`));
    assert.match(context.result, /&lt;script&gt;/);
    assert.doesNotMatch(context.result, /<script>/);
    assert.match(context.result, new RegExp(`data-asset="${asset}"`));
  }
});

test('missing attachments show a warning without an open link', () => {
  const asset = `attachment_${'a'.repeat(32)}.pdf`;
  const context = { content: `[x](../assets/${asset})`, attachments: [{ asset, name: '資料.pdf', size: null }] };
  vm.runInNewContext(`${rendering}\nresult = renderContent(content, [], null, attachments);`, context);
  assert.match(context.result, /添付ファイルが見つかりません/);
  assert.doesNotMatch(context.result, /attachment-open/);
});

test('filename click requests local application opening without navigation', async () => {
  const start = html.indexOf('  async function handleArticleClick(e) {');
  const end = html.indexOf('\n  document.getElementById("cards").addEventListener', start);
  const calls = [];
  const attributes = new Map();
  const link = {
    dataset: { asset: `attachment_${'a'.repeat(32)}.pdf` },
    getAttribute: key => attributes.get(key),
    setAttribute: (key, value) => attributes.set(key, value),
    removeAttribute: key => attributes.delete(key),
  };
  let prevented = false;
  const context = {
    request: async (...args) => { calls.push(args); },
    showError: error => { throw error; },
  };
  vm.runInNewContext(html.slice(start, end), context);
  await context.handleArticleClick({ target: { closest: selector => selector === ".attachment-open" ? link : null }, preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(calls[0][1].headers['X-Fragmentbox-Open'], '1');
  assert.equal(attributes.has('aria-busy'), false);
});

test('editing attachments retain text and successful uploads when a later file fails', async () => {
  const draft = { content: '入力済み', busy: false };
  const calls = [];
  const context = {
    editKey: id => id, editDrafts: new Map([['1', draft]]),
    scopeQuery: () => 'source=inbox', composerReady: true,
    supportedAttachment: () => true, supportedImage: f => f.name.endsWith('.png'),
    imageMaxBytes: 20, attachmentMaxBytes: 100,
    render() {}, closeTagSuggestions() {}, URLSearchParams,
    request: async (url, options) => {
      assert.equal(draft.busy, true);
      calls.push(url);
      if (calls.length === 2) throw new Error('保存失敗');
      return { markdown: '[資料.pdf](/assets/attachment.pdf)  \n' };
    },
  };
  vm.runInNewContext(html.slice(html.indexOf('  function splitEditParts('), html.indexOf('  function renderArticleBody(')), context);
  const code = html.slice(html.indexOf('  async function attachEditFiles('), html.indexOf('  document.getElementById("cards").addEventListener("change"'));
  await vm.runInNewContext(`${code}\nattachEditFiles("1", [{name:"資料.pdf", size:5}, {name:"画像.png", size:5}]);`, context);
  assert.equal(draft.content, '入力済み  \n[資料.pdf](/assets/attachment.pdf)  \n');
  assert.equal(draft.busy, false);
  assert.equal(draft.error, '保存失敗');
  assert.match(calls[0], /^\/api\/attachments\?/);
  assert.match(calls[1], /^\/api\/images\?/);
});

test('only server-recognized tag lines are highlighted; URL anchors remain intact', () => {
  const context = {
    text: '本文 #音楽\nhttps://example.com/#音楽\n## #音楽\n```\n#音楽\n```\n[#音楽](https://example.com)\n\n#音楽 #制作',
  };
  vm.runInNewContext(`${rendering}\nresult = renderContent(text, [], null, [], [8]);`, context);
  assert.equal((context.result.match(/class="tag-inline"/g) || []).length, 2);
  assert.match(context.result, /href="https:\/\/example.com\/#音楽"/);
  assert.match(context.result, /本文 #音楽/);
});


function markdownDocument(content, { imageLinks = [], attachments = [], tagLines = [] } = {}) {
  const context = { content, imageLinks, attachments, tagLines, crypto, marked, DOMPurify };
  vm.runInNewContext(`${rendering}\nresult = renderMarkdownContent(content, imageLinks, "note", attachments, tagLines);`, context);
  return new JSDOM(`<div class="card-body">${context.result}</div>`).window.document;
}

test('Markdown renders headings, emphasis, nested lists, quotes, fenced code, and tables', () => {
  const document = markdownDocument('# 見出し\n\n本文 **太字** *強調* ~~取消~~ `code`\n次の行\n\n- 親\n  - 子\n\n1. 順序\n\n> 引用\n\n```js\nconst x = "<div>";\n```\n\n| 列 | 値 |\n| --- | --- |\n| A | B |');
  for (const selector of ['h1', 'strong', 'em', 'del', 'code', 'br', 'ul ul li', 'ol li', 'blockquote', 'pre code.language-js', 'table th', 'table td']) {
    assert.ok(document.querySelector(selector), selector);
  }
  assert.equal(document.querySelector('pre code').textContent, 'const x = "<div>";\n');
  assert.equal(document.querySelector('h1').textContent, '見出し');
});

test('Markdown only decorates recognized tag lines and leaves code and link labels unchanged', () => {
  const content = '本文 #音楽\n\n`#音楽`\n\n[#音楽](https://example.com/#音楽)\n\n#音楽 #制作';
  const document = markdownDocument(content, { tagLines: [6] });
  assert.equal(document.querySelectorAll('.tag-inline').length, 2);
  assert.equal(document.querySelector('a').textContent, '#音楽');
  assert.equal(document.querySelector('code').textContent, '#音楽');
  assert.equal(document.querySelectorAll('a .tag-inline, code .tag-inline').length, 0);
});

test('Markdown link previews coexist with formatted paragraphs and corrected images', () => {
  const content = '**前**\nhttps://example.com\ntitle: Title\ndescription: Description\n![](../assets/old.webp)\n**後**';
  const document = markdownDocument(content, { imageLinks: [{ original: '../assets/old.webp', status: 'corrected', corrected: '../../assets/new.webp', url: '/assets/new.webp' }] });
  assert.equal(document.querySelectorAll('strong').length, 2);
  assert.equal(document.querySelectorAll('.url-block').length, 1);
  assert.equal(document.querySelector('.url-title').textContent, 'Title');
  assert.equal(document.querySelector('.fragment-image').getAttribute('src'), '/assets/new.webp');
  assert.equal(document.querySelector('.repair-images-btn').dataset.id, 'note');
});

test('Markdown keeps attachment opening and downloading controls', () => {
  const asset = 'attachment_' + 'a'.repeat(32) + '.pdf';
  const document = markdownDocument(`[資料](../assets/${asset})`, { attachments: [{ asset, name: '資料.pdf', size: 2048 }] });
  assert.equal(document.querySelector('.attachment-open').dataset.asset, asset);
  assert.equal(document.querySelector('.attachment-download').getAttribute('download'), '資料.pdf');
});

test('Markdown cannot insert scripts, unsafe URLs, or spoofed application buttons', () => {
  const document = markdownDocument('<script>alert(1)</script>\n\n<button class="delete-btn" data-id="other">delete</button>\n\n[unsafe](javascript:alert%281%29)\n\n![image](javascript:alert%281%29)\n\n![safe](https://example.com/image.png "onerror")');
  assert.equal(document.querySelectorAll('script, .delete-btn, [onerror]').length, 0);
  for (const element of document.querySelectorAll('[href], [src]')) {
    assert.doesNotMatch(element.getAttribute('href') || element.getAttribute('src'), /^javascript:/i);
  }
});

test('fenced metadata and headings remain code without link cards', () => {
  const document = markdownDocument('```md\n# Heading\nhttps://example.com\ntitle: Example\n#tag\n```');
  assert.equal(document.querySelectorAll('.url-block, h1, .tag-inline').length, 0);
  assert.match(document.querySelector('pre').textContent, /title: Example/);
});

test('long articles show 2000 Unicode characters, expand fully, and collapse again', () => {
  const fragment = { id: 'long', content: '😀'.repeat(2000) + '末尾', tag_lines: [] };
  const context = { fragment, expandedArticles: new Set(), editDrafts: new Map(), scopeQuery: () => 'inbox', crypto, marked, DOMPurify };
  vm.createContext(context);
  vm.runInContext(rendering + '\nresult = renderArticleBody(fragment);', context);
  let document = new JSDOM(context.result).window.document;
  assert.equal(document.querySelector('p').textContent, '😀'.repeat(2000));
  assert.equal(document.querySelector('.article-expand-btn').textContent, '続きを読む');
  vm.runInContext('expandedArticles.add(editKey(fragment.id)); result = renderArticleBody(fragment);', context);
  document = new JSDOM(context.result).window.document;
  assert.equal(document.querySelector('p').textContent, fragment.content);
  assert.equal(document.querySelector('.article-expand-btn').textContent, '折りたたむ');
  vm.runInContext('expandedArticles.clear(); result = renderArticleBody(fragment);', context);
  assert.doesNotMatch(context.result, /末尾/);
});

test('short articles need no expansion; cut-off tags are not decorated', () => {
  const context = { fragment: { id: '1', content: 'あ'.repeat(2000), tag_lines: [] }, expandedArticles: new Set(), editDrafts: new Map(), scopeQuery: () => 'inbox', crypto, marked, DOMPurify };
  vm.createContext(context);
  vm.runInContext(rendering + '\nresult = renderArticleBody(fragment);', context);
  assert.doesNotMatch(context.result, /article-expand-btn/);
  context.fragment.content = 'あ'.repeat(1995) + '\n#long_tag';
  context.fragment.tag_lines = [1];
  vm.runInContext('result = renderArticleBody(fragment);', context);
  assert.doesNotMatch(context.result, /tag-inline/);
  assert.match(context.result, /続きを読む/);
});


test('expansion click updates the article, preserves full editing content, and scopes state by folder', () => {
  const fragment = { id: '1', content: 'あ'.repeat(2001) + '末尾', tag_lines: [] };
  const document = new JSDOM('<div class="card"><div class="card-body"></div></div>').window.document;
  const card = document.querySelector('.card');
  card.getBoundingClientRect = () => ({ top: -100 });
  const context = { fragment, allFragments: [fragment], expandedArticles: new Set(), editDrafts: new Map(), scopeQuery: () => 'inbox', crypto, marked, DOMPurify,
    viewerScroll: { scrollTop: 500 }, visibleArticleTop: () => 80, restoringScroll: {}, card };
  vm.createContext(context);
  vm.runInContext(rendering + '\ncard.querySelector(".card-body").innerHTML = renderArticleBody(fragment); toggleArticleExpansion(card.querySelector("button"));', context);
  assert.equal(card.querySelector('button').getAttribute('aria-expanded'), 'true');
  assert.match(card.textContent, /末尾/);
  vm.runInContext('toggleArticleExpansion(card.querySelector("button"));', context);
  assert.equal(card.querySelector('button').getAttribute('aria-expanded'), 'false');
  assert.equal(context.viewerScroll.scrollTop, 320);
  vm.runInContext('expandedArticles.add(editKey(fragment.id));', context);
  context.scopeQuery = () => 'other-folder';
  vm.runInContext('result = renderArticleBody(fragment);', context);
  assert.match(context.result, /続きを読む/);
  vm.runInContext('editDrafts.set(editKey(fragment.id), { content: fragment.content, busy: false }); result = renderArticleBody(fragment);', context);
  assert.match(context.result, /末尾/);
  assert.doesNotMatch(context.result, /article-expand-btn/);
});

function sidebarContext() {
  const dom = new JSDOM(html);
  const context = {
    document: dom.window.document, updateComposer() {}, folderBusy: false, composerBusy: false,
    currentSource: 'inbox', currentFolder: '', folders: [
      { id: 'inbox:', name: 'inbox', source: 'inbox', folder: '', count: 2 },
      { id: 'notes:音楽', name: '音楽', source: 'notes', folder: '音楽', count: 3 },
    ], archiveFolders: [{ name: '音楽', count: 1 }], activeTags: new Set(),
    allFragments: [{ tags: ['音楽', '音楽'] }, { tags: ['音楽', '制作'] }],
    selectFolder() {}, moveFolder() {}, openFolderMenu() {}, openTagRename() {}, renderTagChange() {},
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  function renderFolders('), html.indexOf('  function changeFolderState(')), context);
  vm.runInContext(html.slice(html.indexOf('  function renderTagFilters('), html.indexOf('  document.getElementById("tag-search").addEventListener')), context);
  return { dom, context, document: dom.window.document };
}

test('sidebar switches the visible folder list and preserves General folder management', () => {
  const { dom, context, document } = sidebarContext();
  context.renderFolders();
  assert.equal(document.getElementById('general-link').getAttribute('aria-pressed'), 'true');
  assert.equal(document.getElementById('archive-folders').hidden, true);
  assert.equal(document.getElementById('folder-count').textContent, '2');
  assert.deepEqual([...document.querySelectorAll('#folder-list .folder-count')].map(el => el.textContent), ['2', '3']);
  assert.equal(document.querySelector('#folder-list .folder-name').draggable, true);
  context.currentSource = 'archive';
  context.currentFolder = '音楽';
  context.renderFolders();
  assert.equal(document.getElementById('archive-link').getAttribute('aria-pressed'), 'true');
  assert.equal(document.getElementById('folder-list').hidden, true);
  assert.equal(document.getElementById('archive-folders').hidden, false);
  assert.equal(document.getElementById('folder-count').textContent, '1');
  assert.equal(document.querySelector('#archive-folders .folder-count').textContent, '1');
  assert.equal(document.getElementById('add-folder').hidden, true);
  dom.window.close();
});

test('sidebar tag counts count articles once and tag search updates the visible tag total', () => {
  const { dom, context, document } = sidebarContext();
  context.renderTagFilters(['制作', '音楽']);
  assert.deepEqual([...document.querySelectorAll('.tag-count')].map(el => el.textContent), ['1', '2']);
  assert.equal(document.getElementById('tag-count').textContent, '2');
  document.getElementById('tag-search').value = '制作';
  context.applyTagSearch();
  assert.equal(document.getElementById('tag-count').textContent, '1');
  context.activeTags.add('音楽');
  context.applyTagSearch();
  assert.equal(document.getElementById('tag-count').textContent, '2');
  dom.window.close();
});

test('area switch selects Inbox or Archive, clears tag filters, and is blocked during saving', () => {
  const { dom, context, document } = sidebarContext();
  const loads = [];
  Object.assign(context, {
    fragmentsReady: true, loadVersion: 0, rememberScrollPosition() {}, closeFolderForm() {},
    rememberFolderSelection() {}, render() {}, loadFolders() { loads.push(this.currentSource); },
  });
  vm.runInContext(html.slice(html.indexOf('  function selectArea('), html.indexOf('  document.getElementById("general-link").addEventListener')), context);
  context.currentSource = 'notes';
  context.currentFolder = '音楽';
  context.activeTags.add('音楽');
  document.getElementById('tag-search').value = '音';
  context.selectArea(true);
  assert.equal(context.currentSource, 'archive');
  assert.equal(context.currentFolder, '');
  assert.equal(context.activeTags.size, 0);
  assert.equal(document.getElementById('tag-search').value, '');
  assert.equal(context.fragmentsReady, false);
  assert.equal(loads.length, 1);
  context.composerBusy = true;
  context.selectArea(false);
  assert.equal(context.currentSource, 'archive');
  assert.equal(loads.length, 1);
  context.composerBusy = false;
  context.selectArea(false);
  assert.equal(context.currentSource, 'inbox');
  assert.equal(context.currentFolder, '');
  assert.equal(loads.length, 2);
  dom.window.close();
});

test('Archive initially selects its first folder while an existing selection is retained', async () => {
  for (const selection of ['', '制作']) {
    const loads = [];
    const context = {
      currentSource: 'archive', currentFolder: selection, folders: [], archiveFolders: [], renderFolders() {}, rememberFolderSelection() {},
      async request(url) { return url === '/api/navigation' ? [] : [{ name: '音楽', count: 3 }, { name: '制作', count: 1 }]; },
      async load() { loads.push(context.currentFolder); }, showError(error) { throw error; },
    };
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('  async function loadFolders('), html.indexOf('  document.getElementById("add-folder").addEventListener')), context);
    await context.loadFolders();
    assert.deepEqual(loads, [selection || '音楽']);
  }
});

test('sidebar counts follow loaded articles and edits without resetting counts while loading', () => {
  const { dom, context, document } = sidebarContext();
  context.fragmentsReady = true;
  context.renderFolders();
  context.renderTagFilters(['制作', '音楽']);
  context.allFragments = [{ tags: ['制作', 'favorite'] }];
  context.updateSidebarCounts();
  assert.equal(document.querySelector('#folder-list .folder-count').textContent, '1');
  assert.equal(document.querySelector('[data-tag="favorite"] .tag-count').textContent, '1');
  assert.equal(document.querySelector('[data-tag="音楽"]'), null);
  assert.equal(document.getElementById('tag-count').textContent, '2');
  context.fragmentsReady = false;
  context.allFragments = [];
  context.updateSidebarCounts();
  assert.equal(document.querySelector('#folder-list .folder-count').textContent, '1');
  dom.window.close();
});

test('unknown folder counts stay distinct from real zero before and after sidebar updates', () => {
  const { dom, context, document } = sidebarContext();
  context.folders[0].count = 0;
  delete context.folders[1].count;
  context.archiveFolders[0].count = null;
  context.allFragments = [];
  context.fragmentsReady = true;
  for (const source of ['inbox', 'archive']) {
    context.currentSource = source;
    context.renderFolders();
    const counts = () => [...document.querySelectorAll('.folder-count')].map(el => el.textContent);
    assert.deepEqual(counts(), source === 'inbox' ? ['0', '—'] : ['0', '—', '—']);
    context.updateSidebarCounts();
    assert.deepEqual(counts(), source === 'inbox' ? ['0', '—'] : ['0', '—', '—']);
  }
  dom.window.close();
});


test('navigation refresh retains known counts when an older API omits them and reports the mismatch', async () => {
  const errors = [];
  const context = {
    currentSource: 'inbox', currentFolder: '', folders: [
      { id: 'inbox:', count: 12 }, { id: 'notes:music', count: 4 },
    ], archiveFolders: [{ name: 'music', count: 7 }], renderFolders() {},
    async request() { return [{ id: 'notes:music' }, { id: 'inbox:' }, { id: 'notes:new' }]; },
    async load() {}, showError(error) { errors.push(error.message); },
  };
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('  async function loadFolders('), html.indexOf('  document.getElementById("add-folder").addEventListener')), context);
  await context.loadFolders();
  assert.deepEqual(Array.from(context.folders, folder => folder.count), [4, 12, undefined]);
  assert.equal(context.archiveFolders[0].count, 7);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /再起動/);
  context.request = async () => [{ id: 'notes:music', count: 0 }, { id: 'inbox:', count: 15 }];
  await context.loadFolders();
  assert.deepEqual(Array.from(context.folders, folder => folder.count), [0, 15]);
  assert.equal(errors.length, 1);
});

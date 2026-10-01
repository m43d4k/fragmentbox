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
  const code = html.slice(html.indexOf('  function filtered()'), html.indexOf('  function updateTagButtonAvailability()'));
  const context = { allFragments, matchesFilters: () => true };
  vm.runInNewContext(`${code}\nresult = filtered();`, context);
  assert.deepEqual(Array.from(context.result, f => f.id), ['old', 'middle', 'new']);
  assert.deepEqual(allFragments.map(f => f.id), ['new', 'old', 'middle']);
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
  const start = html.indexOf('  document.getElementById("cards").addEventListener("click", async e => {');
  const end = html.indexOf('\n    if (e.target.', start);
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
    document: { getElementById: () => ({ addEventListener: (_, handler) => { context.handler = handler; } }) },
    request: async (...args) => { calls.push(args); },
    showError: error => { throw error; },
  };
  vm.runInNewContext(html.slice(start, end) + '\n});', context);
  await context.handler({ target: { closest: selector => selector === ".attachment-open" ? link : null }, preventDefault() { prevented = true; } });
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

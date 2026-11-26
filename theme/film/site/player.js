// Media Chrome owns the transport controls. Sample the audio
// clock directly so a seek, stall or rate change always lands on the same frame.
(() => {
  const controller = document.querySelector('media-controller');
  const stage = document.getElementById('stage');
  controller.fullscreenElement = stage;
  setupFullscreen();
  const audio = document.querySelector('audio');
  const cover = document.getElementById('cover');
  const alert = document.getElementById('error');
  let startup;
  let sceneReady = false;
  let lastFrame = -1;
  let animation;

  function setupFullscreen() {
    const button = controller.querySelector('media-fullscreen-button');
    const rotate = document.createElement('button');
    rotate.id = 'rotate';
    rotate.type = 'button';
    rotate.title = /^zh/i.test(navigator.language) ? '旋转画面 90°' : 'Rotate picture 90°';
    rotate.setAttribute('aria-label', rotate.title);
    rotate.setAttribute('aria-pressed', 'false');
    rotate.textContent = '↻';
    button.before(rotate);

    let viewportStyle;
    const frame = window.frameElement;
    const host = frame?.ownerDocument || document;
    function sync() {
      const native = document.fullscreenElement || document.webkitFullscreenElement;
      const active = native === stage || Boolean(viewportStyle);
      stage.classList.toggle('fullscreen', active);
      button.mediaIsFullscreen = active;
      if (!active) {
        stage.classList.remove('turned');
        rotate.setAttribute('aria-pressed', 'false');
      }
    }
    rotate.addEventListener('click', () => {
      rotate.setAttribute('aria-pressed', String(stage.classList.toggle('turned')));
    });

    // Keep the live iframe in place: moving it into a dialog reloads its audio and canvas.
    function enterViewport() {
      if (viewportStyle || (!frame && window !== window.top)) return;
      viewportStyle = host.createElement('style');
      viewportStyle.textContent = `
        html, body { overflow: hidden !important; }
        :has(iframe.tr-film-viewport) { clip-path: none !important; transform: none !important; }
        iframe.tr-film-viewport {
          position: fixed !important; inset: 0 !important; z-index: 2147483647 !important;
          width: 100% !important; height: 100% !important; height: 100dvh !important;
          max-width: none !important; max-height: none !important; aspect-ratio: auto !important;
          margin: 0 !important; padding: 0 !important; border: 0 !important; box-sizing: border-box;
        }`;
      host.head.append(viewportStyle);
      frame?.classList.add('tr-film-viewport');
      if (frame) host.addEventListener('keydown', escape);
      if (frame?.showPopover) {
        frame.popover = 'manual';
        frame.showPopover();
      }
      button.focus({ preventScroll: true });
      sync();
    }
    function exitViewport() {
      if (!viewportStyle) return;
      if (frame?.popover === 'manual') {
        frame.hidePopover();
        frame.removeAttribute('popover');
      }
      if (frame) host.removeEventListener('keydown', escape);
      frame?.classList.remove('tr-film-viewport');
      viewportStyle.remove();
      viewportStyle = null;
      sync();
    }

    // Handle both the control and Media Chrome's F shortcut at their common request.
    async function toggle(event) {
      event.stopPropagation();
      if (viewportStyle) return exitViewport();
      const native = document.fullscreenElement || document.webkitFullscreenElement;
      if (native === stage) {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        return exit.call(document);
      }
      const request = stage.requestFullscreen || stage.webkitRequestFullscreen;
      if (request) {
        try {
          await request.call(stage);
          return;
        } catch { /* The browser may expose the API but decline the request. */ }
      }
      enterViewport();
    }
    for (const name of ['mediaenterfullscreenrequest', 'mediaexitfullscreenrequest']) {
      stage.addEventListener(name, toggle, true);
    }
    for (const name of ['fullscreenchange', 'webkitfullscreenchange']) {
      document.addEventListener(name, sync);
    }
    function escape(event) {
      if (viewportStyle && event.key === 'Escape' && !event.defaultPrevented) exitViewport();
    }
    document.addEventListener('keydown', escape);
    window.addEventListener('pagehide', exitViewport);
  }

  function fail(error) {
    sceneReady = false;
    audio.pause();
    console.error(error);
    alert.textContent = /^zh/i.test(navigator.language) ? '影片加载失败。' : 'The film could not be loaded.';
    alert.hidden = false;
  }

  function draw() {
    cancelAnimationFrame(animation);
    if (!sceneReady || document.hidden) return;
    const time = audio.currentTime;
    const frame = Math.floor(time * FPS);
    if (frame !== lastFrame) {
      try {
        renderAt(time);
      } catch (error) {
        fail(error);
        return;
      }
      lastFrame = frame;
      cover.hidden = true;
    }
    if (!audio.paused && !audio.ended) animation = requestAnimationFrame(draw);
  }

  function activate() {
    startup ??= boot().then(() => {
      sceneReady = true;
      draw();
    }).catch(fail);
  }

  // Chapters (a long film's parts): DATA.chapters comes from script.json, timed by the measured timeline; the
  // same cues reach the time range through the <track kind="chapters"> that theme/film/build.py adds.
  const marks = (window.DATA && window.DATA.chapters) || [];
  const chapterButton = document.getElementById('chapters-button');
  const chapterMenu = document.getElementById('chapters');
  if (marks.length && chapterButton && chapterMenu) {
    const clock = t => { const s = Math.floor(t); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
    const items = marks.map(m => {
      const item = document.createElement('li');
      const go = document.createElement('button');
      go.type = 'button';
      for (const [cls, text, lang] of [['time', clock(m.start), ''], ['en', m.en, 'en'], ['zh', m.zh, 'zh']]) {
        const span = document.createElement('span');
        span.className = cls;
        span.textContent = text;
        if (lang) span.lang = lang;
        go.append(span);
      }
      go.addEventListener('click', () => {
        audio.currentTime = m.start;
        showChapters(false);
        chapterButton.focus();
      });
      item.append(go);
      chapterMenu.querySelector('ol').append(item);
      return item;
    });
    const currentChapter = () => {
      let k = 0;
      marks.forEach((m, i) => { if (audio.currentTime >= m.start - 0.05) k = i; });
      return k;
    };
    const markCurrent = () => {
      const k = currentChapter();
      items.forEach((item, i) => (i === k ? item.setAttribute('aria-current', 'true') : item.removeAttribute('aria-current')));
    };
    function showChapters(open) {
      chapterMenu.hidden = !open;
      chapterButton.setAttribute('aria-expanded', String(open));
      if (open) items[currentChapter()].querySelector('button').focus();
    }
    chapterButton.hidden = false;
    chapterButton.addEventListener('click', () => showChapters(chapterMenu.hidden));
    chapterMenu.addEventListener('keydown', event => {
      if (event.key === 'Escape') { showChapters(false); chapterButton.focus(); }
    });
    for (const event of ['timeupdate', 'seeked']) audio.addEventListener(event, markCurrent);
    markCurrent();
  }

  for (const event of ['play', 'seeking']) audio.addEventListener(event, activate);
  for (const event of ['playing', 'pause', 'seeked', 'ended']) audio.addEventListener(event, draw);
  audio.addEventListener('error', () => fail(audio.error));
  document.addEventListener('visibilitychange', draw);
})();

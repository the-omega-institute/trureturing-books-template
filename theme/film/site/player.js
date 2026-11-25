// Media Chrome owns the transport and fullscreen controls. Sample the audio
// clock directly so a seek, stall or rate change always lands on the same frame.
(() => {
  const controller = document.querySelector('media-controller');
  controller.fullscreenElement = document.getElementById('stage');
  const audio = document.querySelector('audio');
  const cover = document.getElementById('cover');
  const alert = document.getElementById('error');
  let startup;
  let sceneReady = false;
  let lastFrame = -1;
  let animation;

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

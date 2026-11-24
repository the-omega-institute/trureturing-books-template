// Media Chrome owns the transport and fullscreen controls. Sample the audio
// clock directly so a seek, stall or rate change always lands on the same frame.
(() => {
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

  for (const event of ['play', 'seeking']) audio.addEventListener(event, activate);
  for (const event of ['playing', 'pause', 'seeked', 'ended']) audio.addEventListener(event, draw);
  audio.addEventListener('error', () => fail(audio.error));
  document.addEventListener('visibilitychange', draw);
})();

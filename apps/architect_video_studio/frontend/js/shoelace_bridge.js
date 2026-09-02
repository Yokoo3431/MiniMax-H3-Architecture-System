/* AVS compatibility bridge: retain existing vanilla event contracts while
   presentation controls are rendered by Shoelace Web Components. */
(function () {
  function bridge(source, target) {
    document.addEventListener(source, (event) => {
      const control = event.target;
      if (!control || typeof control.dispatchEvent !== 'function') return;
      control.dispatchEvent(new Event(target, {bubbles: true}));
    });
  }
  bridge('sl-change', 'change');
  bridge('sl-input', 'input');
})();
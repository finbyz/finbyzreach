/* Paste the snippet from Subscription Center Settings on an external website. */
(function () {
    const containers = document.querySelectorAll('[data-finbyzreach-subscription-form]');
    containers.forEach((container) => {
        if (container.querySelector('iframe')) return;
        const source = container.getAttribute('data-src');
        if (!source) return;
        let origin;
        try {
            origin = new URL(source).origin;
        } catch (error) {
            return;
        }
        const frame = document.createElement('iframe');
        frame.src = source;
        frame.title = 'Email subscriptions';
        frame.loading = 'lazy';
        frame.style.width = '100%';
        frame.style.height = '720px';
        frame.style.border = '0';
        frame.style.display = 'block';
        container.replaceChildren(frame);
        window.addEventListener('message', (event) => {
            if (event.origin !== origin || event.source !== frame.contentWindow) return;
            if (!event.data || event.data.type !== 'finbyzreach:subscription-form-height') return;
            const height = Number(event.data.height);
            if (Number.isFinite(height)) frame.style.height = Math.max(300, Math.min(5000, Math.ceil(height))) + 'px';
        });
    });
})();

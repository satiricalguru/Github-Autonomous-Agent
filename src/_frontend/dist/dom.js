/** External data is always text; links must identify real GitHub pull requests. */
export function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
export function githubPrUrl(value) {
    try {
        const url = new URL(String(value));
        return url.protocol === 'https:' && url.hostname === 'github.com' && !url.username && !url.password && /^\/[\w.-]+\/[\w.-]+\/pull\/\d+$/.test(url.pathname) ? url.href : null;
    }
    catch {
        return null;
    }
}
//# sourceMappingURL=dom.js.map
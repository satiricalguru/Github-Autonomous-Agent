/**
 * Web Audio API Sound Synthesizer
 * Provides subtle, tactical audio feedback for operator actions.
 */
class SoundSynthesizer {
    ctx = null;
    enabled = false;
    constructor() {
        const saved = localStorage.getItem('sound_enabled');
        this.enabled = saved === 'true';
    }
    initContext() {
        if (!this.ctx && typeof window !== 'undefined') {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (AudioCtx) {
                this.ctx = new AudioCtx();
            }
        }
        if (this.ctx && this.ctx.state === 'suspended') {
            this.ctx.resume().catch(() => { });
        }
        return this.ctx;
    }
    isEnabled() {
        return this.enabled;
    }
    toggle() {
        this.enabled = !this.enabled;
        localStorage.setItem('sound_enabled', String(this.enabled));
        if (this.enabled) {
            this.initContext();
            this.playSuccess();
        }
        return this.enabled;
    }
    playClick() {
        if (!this.enabled)
            return;
        const ctx = this.initContext();
        if (!ctx)
            return;
        try {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(800, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(400, ctx.currentTime + 0.04);
            gain.gain.setValueAtTime(0.04, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.04);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.04);
        }
        catch {
            // AudioContext policy suppression fallback
        }
    }
    playToggle() {
        if (!this.enabled)
            return;
        const ctx = this.initContext();
        if (!ctx)
            return;
        try {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'triangle';
            osc.frequency.setValueAtTime(320, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(640, ctx.currentTime + 0.08);
            gain.gain.setValueAtTime(0.05, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.08);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.08);
        }
        catch { }
    }
    playSuccess() {
        if (!this.enabled)
            return;
        const ctx = this.initContext();
        if (!ctx)
            return;
        try {
            const now = ctx.currentTime;
            [523.25, 659.25, 783.99].forEach((freq, idx) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(freq, now + idx * 0.06);
                gain.gain.setValueAtTime(0.04, now + idx * 0.06);
                gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.06 + 0.12);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now + idx * 0.06);
                osc.stop(now + idx * 0.06 + 0.12);
            });
        }
        catch { }
    }
    playAlert() {
        if (!this.enabled)
            return;
        const ctx = this.initContext();
        if (!ctx)
            return;
        try {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(220, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(110, ctx.currentTime + 0.15);
            gain.gain.setValueAtTime(0.05, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.15);
        }
        catch { }
    }
}
export const sound = new SoundSynthesizer();
//# sourceMappingURL=audio.js.map
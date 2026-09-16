/**
 * State Management Store for Mission Control
 */
class Store {
    state = {
        currentTab: 'overview',
        status: null,
        selectedTask: null,
        isDrawerOpen: false,
        isShortcutsOpen: false,
        theme: localStorage.getItem('theme') || 'dark',
        taskFilter: 'all',
        searchQuery: '',
        autoscrollTerminal: true,
        isLoading: false,
        lastError: null
    };
    listeners = new Set();
    getState() {
        return this.state;
    }
    setState(patch) {
        this.state = { ...this.state, ...patch };
        this.notify();
    }
    subscribe(listener) {
        this.listeners.add(listener);
        listener(this.state);
        return () => {
            this.listeners.delete(listener);
        };
    }
    notify() {
        for (const listener of this.listeners) {
            listener(this.state);
        }
    }
}
export const store = new Store();
//# sourceMappingURL=state.js.map
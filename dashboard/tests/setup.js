import "@testing-library/jest-dom";

// jsdom does not implement ResizeObserver, which Recharts' ResponsiveContainer requires.
global.ResizeObserver = class ResizeObserver {
  constructor(callback) {
    this.callback = callback;
  }
  observe() {}
  unobserve() {}
  disconnect() {}
};

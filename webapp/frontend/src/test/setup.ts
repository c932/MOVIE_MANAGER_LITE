import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
afterEach(cleanup);
Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable: true, value() { this.setAttribute('open', ''); }});
Object.defineProperty(HTMLDialogElement.prototype, 'close', {configurable: true, value() { this.removeAttribute('open'); }});
Object.defineProperty(window, 'matchMedia', {writable: true, value: vi.fn(() => ({matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn()}))});

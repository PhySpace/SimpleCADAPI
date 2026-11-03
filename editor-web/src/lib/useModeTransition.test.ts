import { describe, expect, it } from 'vitest';

import { sideStyle } from './useModeTransition';

describe('the side panels of a mode change', () => {
  it('leave to the left and the right, wait off-screen, then come back', () => {
    expect(sideStyle('idle', -1)).toBeUndefined();
    expect(sideStyle('out', -1)?.transform).toBe('translateX(-108%)');
    expect(sideStyle('out', 1)?.transform).toBe('translateX(108%)');
    expect(sideStyle('pre', 1)).toMatchObject({ transform: 'translateX(108%)', transition: 'none' });
    expect(sideStyle('in', -1)?.transform).toBe('translateX(0)');
  });
  it('leaves with an ease-in and arrives with a decelerating curve', () => {
    expect(String(sideStyle('out', 1)?.transition)).toContain('cubic-bezier(0.55');
    expect(String(sideStyle('in', 1)?.transition)).toContain('cubic-bezier(0.12');
  });
});

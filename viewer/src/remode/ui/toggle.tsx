import * as React from 'react';
import * as ToggleGroupPrimitive from '@radix-ui/react-toggle-group';
import * as TogglePrimitive from '@radix-ui/react-toggle';

import { cn } from './lib/utils';

const toggleStyles =
  'inline-flex h-7 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 font-mono text-[9px] tracking-[0.06em] text-dim uppercase outline-none transition-colors hover:bg-white/5 hover:text-ink data-[state=on]:border-lime/25 data-[state=on]:bg-lime/10 data-[state=on]:text-lime [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*="size-"])]:size-3';

function Toggle({ className, ...props }: React.ComponentProps<typeof TogglePrimitive.Root>) {
  return <TogglePrimitive.Root data-slot="toggle" className={cn(toggleStyles, className)} {...props} />;
}

function ToggleGroup({ className, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Root>) {
  return <ToggleGroupPrimitive.Root data-slot="toggle-group" className={cn('flex items-center gap-0.5', className)} {...props} />;
}

function ToggleGroupItem({ className, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Item>) {
  return <ToggleGroupPrimitive.Item data-slot="toggle-group-item" className={cn(toggleStyles, className)} {...props} />;
}

export { Toggle, ToggleGroup, ToggleGroupItem, toggleStyles };

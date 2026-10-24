import * as React from 'react';
import { Group, Panel, Separator } from 'react-resizable-panels';

import { cn } from './lib/utils';

function Resizable({ className, ...props }: React.ComponentProps<typeof Group>) {
  return <Group data-slot="resizable" className={cn('h-full w-full', className)} {...props} />;
}

function ResizablePanel({ className, ...props }: React.ComponentProps<typeof Panel>) {
  return <Panel data-slot="resizable-panel" className={cn('min-h-0 min-w-0', className)} {...props} />;
}

/** Hairline splitter that lights up lime on hover/drag. Column handle in a
 *  horizontal group, row handle in a vertical group. */
function ResizableHandle({ className, children, ...props }: React.ComponentProps<typeof Separator>) {
  return (
    <Separator
      data-slot="resizable-handle"
      className={cn(
        'relative bg-void outline-none transition-colors duration-150',
        'data-[separator=hover]:bg-lime/30 data-[separator=focus]:bg-lime/50 data-[separator=active]:bg-lime',
        className,
      )}
      {...props}
    >
      {children}
    </Separator>
  );
}

/** Thin hairline centered inside a handle. */
function HandleLine({ vertical = false }: { vertical?: boolean }) {
  return vertical ? (
    <span className="pointer-events-none absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line" />
  ) : (
    <span className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line" />
  );
}

export { Resizable, ResizablePanel, ResizableHandle, HandleLine };

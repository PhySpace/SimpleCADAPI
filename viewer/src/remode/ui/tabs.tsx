import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';

import { cn } from './lib/utils';

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn('flex flex-col', className)} {...props} />;
}

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn('inline-flex shrink-0 items-center gap-0.5 border-b border-line bg-panel px-2', className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-none border-b-2 border-transparent px-3 py-2.5 font-mono text-[9px] tracking-[0.08em] text-dim uppercase outline-none transition-colors hover:bg-white/[0.03] hover:text-ink data-[state=active]:border-lime data-[state=active]:bg-transparent data-[state=active]:text-lime [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*="size-"])]:size-3',
        className,
      )}
      {...props}
    />
  );
}

/** forceMount'd panels stay mounted (CodeMirror / three.js hosts must not
 *  unmount); visibility is driven purely by data-state. */
function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn('flex-1 min-h-0 min-w-0 outline-none data-[state=inactive]:hidden', className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent };

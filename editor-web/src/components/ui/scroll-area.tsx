import * as React from "react";
import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area";

import { cn } from "@/lib/utils";

/** Scrolls without a visible bar until the pointer is over it. */
function ScrollArea({ className, children, ...props }: React.ComponentProps<typeof ScrollAreaPrimitive.Root>) {
  return (
    <ScrollAreaPrimitive.Root type="hover" scrollHideDelay={400} className={cn("relative overflow-hidden", className)} {...props}>
      {/* Radix sets `display: table` inline on the viewport, which lets wide
          children (code editors) stretch the panel. Force block + full width
          so inner scrollers own the overflow instead. */}
      <ScrollAreaPrimitive.Viewport className="h-full w-full [&>div]:!block">{children}</ScrollAreaPrimitive.Viewport>
      <ScrollBar />
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  );
}

function ScrollBar({ className, ...props }: React.ComponentProps<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>) {
  return (
    <ScrollAreaPrimitive.ScrollAreaScrollbar
      orientation="vertical"
      className={cn("flex w-[6px] touch-none select-none border-l border-transparent p-0 transition-opacity", className)}
      {...props}
    >
      <ScrollAreaPrimitive.ScrollAreaThumb className="relative flex-1 bg-scrollbar hover:bg-scrollbar-hover" />
    </ScrollAreaPrimitive.ScrollAreaScrollbar>
  );
}

export { ScrollArea, ScrollBar };

import * as React from "react";
import { Group, Panel, Separator } from "react-resizable-panels";

import { cn } from "@/lib/utils";

/** Horizontal split container: <ResizablePanelGroup><ResizablePanel/>… */
function ResizablePanelGroup({
  className,
  ...props
}: React.ComponentProps<typeof Group>) {
  return <Group orientation="horizontal" className={cn("flex h-full w-full", className)} {...props} />;
}

const ResizablePanel = Panel;

function ResizableHandle({
  className,
  ...props
}: React.ComponentProps<typeof Separator>) {
  return (
    <Separator
      className={cn(
        "relative w-[3px] shrink-0 bg-border transition-colors hover:bg-primary/50",
        className,
      )}
      {...props}
    />
  );
}

export { ResizablePanelGroup, ResizablePanel, ResizableHandle };

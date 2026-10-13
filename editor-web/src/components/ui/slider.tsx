import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";

/** A flat rule with a square handle; the range turns orange once the value
 * differs from the source (`modified`). */
function Slider({
  className,
  modified,
  ...props
}: React.ComponentProps<typeof SliderPrimitive.Root> & { modified?: boolean }) {
  return (
    <SliderPrimitive.Root
      className={cn("relative flex h-4 w-full touch-none select-none items-center", className)}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-[2px] w-full grow overflow-hidden bg-input">
        <SliderPrimitive.Range className={cn("absolute h-full", modified ? "bg-focus" : "bg-primary")} />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        className={cn(
          "block h-3 w-2 border-2 bg-background transition-colors focus-visible:outline-none focus-visible:border-focus disabled:pointer-events-none disabled:opacity-50",
          modified ? "border-focus" : "border-primary",
        )}
      />
    </SliderPrimitive.Root>
  );
}

export { Slider };

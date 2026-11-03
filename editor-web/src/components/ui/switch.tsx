import * as React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";

import { cn } from "@/lib/utils";

function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center border-2 border-input bg-background transition-colors focus-visible:border-focus focus-visible:outline-none data-[state=checked]:border-primary data-[state=checked]:bg-primary",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-3 translate-x-0.5 bg-foreground transition-transform data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-primary-foreground" />
    </SwitchPrimitive.Root>
  );
}

export { Switch };

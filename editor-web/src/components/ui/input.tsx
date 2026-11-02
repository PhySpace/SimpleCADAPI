import * as React from "react";

import { cn } from "@/lib/utils";

const field =
  "w-full border-2 border-input bg-background px-2 text-[12px] text-foreground placeholder:text-muted-foreground focus-visible:border-focus focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-fail";

function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input className={cn(field, "h-7", className)} {...props} />;
}

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return <textarea className={cn(field, "min-h-20 py-1 leading-5", className)} {...props} />;
}

export { Input, Textarea };

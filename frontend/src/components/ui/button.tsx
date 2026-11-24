import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva("btn inline-flex items-center justify-center gap-2 disabled:pointer-events-none disabled:opacity-50", {
  variants: { variant: { default: "primary", outline: "", ghost: "ghost" }, size: { default: "", sm: "sm", lg: "big" } },
  defaultVariants: { variant: "default", size: "default" },
});
export function Button({ className, variant, size, asChild = false, type = "button", ...props }: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp data-slot="button" type={type} className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

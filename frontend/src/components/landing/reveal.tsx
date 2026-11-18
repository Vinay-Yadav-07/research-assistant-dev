"use client";

import { motion } from "motion/react";
import type { ReactNode } from "react";

/** Fades content up once when it enters the viewport (DESIGN.md §7: 12–16 px, 60–80 ms stagger). */
export function Reveal({
  children,
  index = 0,
  className,
}: {
  children: ReactNode;
  index?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -10% 0px" }}
      transition={{
        duration: 0.6,
        delay: index * 0.07,
        ease: [0.23, 1, 0.32, 1],
      }}
    >
      {children}
    </motion.div>
  );
}

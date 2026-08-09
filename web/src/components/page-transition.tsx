"use client";

import { type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";

type PageTransitionProps = {
  children: ReactNode;
  pathname: string;
};

const pageVariants = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

const pageTransition = {
  duration: 0.2,
  ease: [0.25, 0.1, 0.25, 1] as [number, number, number, number],
};

export function PageTransition({ children, pathname }: PageTransitionProps) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={pathname}
        variants={pageVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        transition={pageTransition}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
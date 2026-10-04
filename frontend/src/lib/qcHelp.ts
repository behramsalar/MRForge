/** What to look for in each QC result, in plain language. QC only shows; the researcher decides. */
export const qcHelp: { match: RegExp; text: string }[] = [
  {
    match: /^Head motion/,
    text: "The lines should stay close to zero. In the lowest plot, jumps above the red dashed line mean the head moved a lot at that moment. This is a warning sign only: you decide whether to keep the data.",
  },
  {
    match: /^Registration to the T1/,
    text: "Top row: the functional image with the brain-tissue boundary of the T1 in red. Bottom row: the T1 with the edges of the functional image in red. The red lines should follow the folds of the brain in both rows.",
  },
  {
    match: /^Distortion correction/,
    text: "Top: before the correction. Bottom: after. The red outline should fit the folds better in the bottom row, especially at the front and underside of the brain.",
  },
  {
    match: /^Alignment to standard space/,
    text: "The red line is the outline of the standard (MNI) brain. It should follow the edge of the brain in every view.",
  },
];

export function helpFor(name: string): string | undefined {
  return qcHelp.find((h) => h.match.test(name))?.text;
}

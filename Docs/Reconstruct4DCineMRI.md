# Reconstruct 4D cine-MRI

## Summary

This module reconstructs a 4D volume (sequence of 3D Cartesian volumes) from a sparse set of cine-MRI frames. Image frames are typically acquired in a rotating frame pattern. See [demo video on YouTube](https://youtu.be/hIxr9OKBvQ8).

[![](https://img.youtube.com/vi/hIxr9OKBvQ8/0.jpg)](https://youtu.be/hIxr9OKBvQ8 "Demo video of volume reconstruction from sparse frame set")

## Usage

### Setup

- Install Slicer
- Start Slicer, install SlicerHeart and SlicerIGSIO extensions from the Extensions Manager
- Restart Slicer

### Reconstruct 4D volume from cine-MRI frames

- Import the cine-MRI acquisition using the DICOM module: switch to DICOM module and drag-and-drop the folder that contains the DICOM files to the application window
- Load the cine-MRI data set by double-clicking on the cine-MRI series in the DICOM browser
- Create an Annotation ROI node: click the down-arrow in the "Create and place" button on the toolbar, choose the "ROI" option at the top, then click in the middle of the region of interest in a slice view, then at a corner of a region of interest in the same slice view.
- Switch to "Reconstruct 4D cine-MRI" module
- Select the loaded cine-MRI sequence as "Input sequence"
- Select the created ROI node as "Input region"
- Optional: Adjust the "Output spacing" to adjust the resolution of the reconstructed volume. Smaller values results in finer details but longer reconstruction time and potentially more unfilled holes in the reconstructed volume.
- Click Apply to reconstruct the volume.
- Click the "Play" button in the toolbar to view the reconstructed volume sequence.

### Reconstruct volume with custom frame grouping

By default, the module automatically determines how to order and group frames to make up volumes. For this, it assumed that:
- ECG-gated images are acquired throughout multiple cardiac cycles. First N frames are acquired in the first frame position/orientation, then N frames are acquired in the second frame position/orientation, etc.
- The "Trigger Time" DICOM field is reset to the starting value when changing position/orientation (and the trigger value is increasing through the cardiac cycle).

If these assumptions are not correct then it is necessary to specify the index of each frame that make up each volume:
- Open "Advanced" section
- Disable "auto-detect"
- Type the list of frame indices (integer values, starting with 0), for each volume that will be reconstructed. Frame indices for an output volume are separated by spaces, indices are in a row for each output volume.

Example: 30 volumes (cardiac phases), each is made up of 18 frames

```txt
0 30 60 90 120 150 180 210 240 270 300 330 360 390 420 450 480 510
1 31 61 91 121 151 181 211 241 271 301 331 361 391 421 451 481 511
2 32 62 92 122 152 182 212 242 272 302 332 362 392 422 452 482 512
3 33 63 93 123 153 183 213 243 273 303 333 363 393 423 453 483 513
4 34 64 94 124 154 184 214 244 274 304 334 364 394 424 454 484 514
5 35 65 95 125 155 185 215 245 275 305 335 365 395 425 455 485 515
6 36 66 96 126 156 186 216 246 276 306 336 366 396 426 456 486 516
7 37 67 97 127 157 187 217 247 277 307 337 367 397 427 457 487 517
8 38 68 98 128 158 188 218 248 278 308 338 368 398 428 458 488 518
9 39 69 99 129 159 189 219 249 279 309 339 369 399 429 459 489 519
10 40 70 100 130 160 190 220 250 280 310 340 370 400 430 460 490 520
11 41 71 101 131 161 191 221 251 281 311 341 371 401 431 461 491 521
12 42 72 102 132 162 192 222 252 282 312 342 372 402 432 462 492 522
13 43 73 103 133 163 193 223 253 283 313 343 373 403 433 463 493 523
14 44 74 104 134 164 194 224 254 284 314 344 374 404 434 464 494 524
15 45 75 105 135 165 195 225 255 285 315 345 375 405 435 465 495 525
16 46 76 106 136 166 196 226 256 286 316 346 376 406 436 466 496 526
17 47 77 107 137 167 197 227 257 287 317 347 377 407 437 467 497 527
18 48 78 108 138 168 198 228 258 288 318 348 378 408 438 468 498 528
19 49 79 109 139 169 199 229 259 289 319 349 379 409 439 469 499 529
20 50 80 110 140 170 200 230 260 290 320 350 380 410 440 470 500 530
21 51 81 111 141 171 201 231 261 291 321 351 381 411 441 471 501 531
22 52 82 112 142 172 202 232 262 292 322 352 382 412 442 472 502 532
23 53 83 113 143 173 203 233 263 293 323 353 383 413 443 473 503 533
24 54 84 114 144 174 204 234 264 294 324 354 384 414 444 474 504 534
25 55 85 115 145 175 205 235 265 295 325 355 385 415 445 475 505 535
26 56 86 116 146 176 206 236 266 296 326 356 386 416 446 476 506 536
27 57 87 117 147 177 207 237 267 297 327 357 387 417 447 477 507 537
28 58 88 118 148 178 208 238 268 298 328 358 388 418 448 478 508 538
29 59 89 119 149 179 209 239 269 299 329 359 389 419 449 479 509 539
```

## Information for Developers

The module is implemented as a scripted module. Source code is available at:

https://github.com/SlicerHeart/SlicerHeart/tree/master/Reconstruct4DCineMRI

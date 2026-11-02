import React from "react";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, it, expect, vi } from "vitest";
import { Markdown } from "./markdown";
afterEach(cleanup);
it("renders inline and display equations without enabling unsafe math links", () => {
  const { container } = render(
    <Markdown
      text={
        "Speedup $S = \\frac{120}{20} = 6$.\n\n$$\nE = \\frac{6}{8} = 0.75\n$$\n\n$\\href{javascript:alert(1)}{bad}$"
      }
    />,
  );
  expect(container.querySelector(".katex")).toBeTruthy();
  expect(container.querySelector(".katex-display")).toBeTruthy();
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
});
it("renders tables/code, filters executable content, and links real source IDs", () => {
  const clicked = vi.fn();
  const { container } = render(
    <Markdown
      text={
        "<script>alert(1)</script>\n\n[bad](javascript:alert)\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n```js\nconst x = 1\n```\n\n[source:11111111-1111-1111-1111-111111111111]"
      }
      onSource={clicked}
    />,
  );
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  expect(container.querySelector("table")).toBeTruthy();
  expect(screen.getByLabelText("Copy code")).toBeTruthy();
  fireEvent.click(screen.getByText("Source ↗"));
  expect(clicked).toHaveBeenCalledWith("11111111-1111-1111-1111-111111111111");
});
it("renders provider web citation tags as links only for returned search URLs", () => {
  render(
    <Markdown
      text="Official docs [url: https://docs.python.org/]"
      allowedUrls={["https://docs.python.org/"]}
    />,
  );
  expect(
    screen.getByRole("link", { name: "Source ↗" }).getAttribute("href"),
  ).toBe("https://docs.python.org/");
  expect(screen.queryByText(/\[url:/)).toBeNull();
});

import { BellIcon, MoonIcon, SunIcon } from "@radix-ui/react-icons";
import { Avatar, Badge, DropdownMenu, Flex, IconButton, Popover, Text } from "@radix-ui/themes";
import { latestJobs, stepName } from "../components/JobsPanel";
import { StatusBadge } from "../components/ui/Badges";
import { href, type Route } from "../lib/router";
import { space, type } from "../theme/tokens";
import { crumbs } from "./nav";
import { useResearcher } from "./ResearcherProvider";
import { useAppTheme } from "./ThemeProvider";
import { useWorkspace } from "./WorkspaceContext";

/** The bell: what is running now and what needs attention, from the live workspace state. */
function Activity({ ws }: { ws: string }) {
  const { state, connected } = useWorkspace();
  const jobs = latestJobs(state?.jobs ?? []);
  const running = (state?.operations ?? []).filter((o) => o.status === "Queued" || o.status === "Running");
  const attention = jobs.filter((j) => j.status === "Failed" || j.status === "Interrupted");
  const waiting = jobs.filter((j) => j.status === "Waiting");
  const count = running.length + attention.length + waiting.length;
  return (
    <Popover.Root>
      <Popover.Trigger>
        <IconButton variant="ghost" color="gray" aria-label={`Activity, ${count} items`} style={{ position: "relative" }}>
          <BellIcon width={18} height={18} />
          {count > 0 && (
            <Badge
              size="1"
              radius="full"
              color={attention.length ? "red" : "orange"}
              variant="solid"
              style={{ position: "absolute", top: -6, right: -8 }}
            >
              {count}
            </Badge>
          )}
        </IconButton>
      </Popover.Trigger>
      <Popover.Content width="340px">
        <Flex direction="column" gap={space.group}>
          <Text weight="bold" size={type.body}>
            Activity
          </Text>
          {!connected && (
            <Text size={type.help} color="orange">
              Reconnecting to MRForge…
            </Text>
          )}
          {count === 0 && (
            <Text size={type.help} color="gray">
              Nothing is running and nothing needs attention.
            </Text>
          )}
          {running.map((o) => (
            <Flex key={o.id} justify="between" gap={space.group} align="center">
              <Text size={type.help}>
                {o.title}
                {o.started_by ? ` · ${o.started_by}` : ""}
              </Text>
              <StatusBadge status="Running" />
            </Flex>
          ))}
          {waiting.map((j) => (
            <Flex key={j.id} justify="between" gap={space.group} align="center">
              <a href={href(ws, "process", "ica")}>
                <Text size={type.help}>
                  Label the components{j.run ? ` of ${j.run}` : ""} ({j.subject})
                </Text>
              </a>
              <StatusBadge status="Waiting" />
            </Flex>
          ))}
          {attention.map((j) => (
            <Flex key={j.id} justify="between" gap={space.group} align="center">
              <Text size={type.help}>
                {stepName[j.step] ?? j.step}
                {j.run ? ` (${j.run})` : ""}
                {j.started_by ? ` · ${j.started_by}` : ""}
              </Text>
              <StatusBadge status={j.status} />
            </Flex>
          ))}
          <a href={href(ws, "jobs")}>
            <Text size={type.help}>See all jobs</Text>
          </a>
        </Flex>
      </Popover.Content>
    </Popover.Root>
  );
}

function initials(name: string): string {
  const parts = name.split(" ").filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "")).toUpperCase();
}

/** Who is working. Not a login: switching the profile only changes whose work is shown. */
function ResearcherMenu() {
  const { researcher, researchers, openPicker } = useResearcher();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <IconButton variant="ghost" color="gray" radius="full" aria-label="Researcher">
          <Avatar size="2" radius="full" fallback={researcher ? initials(researcher.name) : "?"} color="orange" />
        </IconButton>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end">
        <DropdownMenu.Label>{researcher ? `Working as ${researcher.name}` : "No researcher chosen"}</DropdownMenu.Label>
        {researchers.length > 0 && <DropdownMenu.Separator />}
        <DropdownMenu.Item onSelect={openPicker}>{researcher ? "Switch researcher" : "Choose your name"}</DropdownMenu.Item>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}

export function TopBar({ route }: { route: Route }) {
  const { appearance, toggle } = useAppTheme();
  return (
    <header className="topbar">
      <Flex align="center" gap={space.inline}>
        {route.workspace && (
          <>
            <a href={href(route.workspace, "dashboard")} style={{ textDecoration: "none" }}>
              <Text size={type.help} color="gray">
                {route.workspace}
              </Text>
            </a>
            <Text size={type.help} color="gray">
              /
            </Text>
          </>
        )}
        {crumbs(route.page, route.extra).map((c, i, all) => (
          <Flex key={c} align="center" gap={space.inline}>
            {i > 0 && (
              <Text size={type.help} color="gray">
                /
              </Text>
            )}
            <Text size={type.body} weight={i === all.length - 1 ? "bold" : "regular"}>
              {c}
            </Text>
          </Flex>
        ))}
      </Flex>
      <Flex align="center" gap={space.group}>
        {route.workspace && <Activity ws={route.workspace} />}
        <IconButton
          variant="ghost"
          color="gray"
          onClick={toggle}
          aria-label={appearance === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {appearance === "dark" ? <SunIcon width={18} height={18} /> : <MoonIcon width={18} height={18} />}
        </IconButton>
        <ResearcherMenu />
      </Flex>
    </header>
  );
}

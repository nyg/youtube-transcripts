import { useEffect, useState } from "react"

import { useChannels } from "@/api/queries"
import { ChannelManagerDialog } from "@/components/ChannelManagerDialog"
import { AskTab } from "@/components/AskTab"
import { ChannelSelect } from "@/components/ChannelSelect"
import { MentionsTab } from "@/components/MentionsTab"
import { MonitorStatus } from "@/components/MonitorStatus"
import { PriceNotice } from "@/components/PriceNotice"
import { ProcessTab } from "@/components/ProcessTab"
import { PromptManagerDialog } from "@/components/PromptManagerDialog"
import { SearchTab } from "@/components/SearchTab"
import { SettingsDialog } from "@/components/SettingsDialog"
import { SummaryList } from "@/components/SummaryList"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

function App() {
  const { data: channels } = useChannels()
  const [channelId, setChannelId] = useState<number | null>(() => {
    const saved = localStorage.getItem("channelId")
    return saved ? Number(saved) : null
  })
  const [manageOpen, setManageOpen] = useState(false)
  const [promptsOpen, setPromptsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Keep the selection valid as channels are added/removed.
  useEffect(() => {
    if (!channels) return
    if (channels.length === 0) {
      setChannelId(null)
    } else if (channelId === null || !channels.some((c) => c.id === channelId)) {
      setChannelId(channels[0].id)
    }
  }, [channels, channelId])

  useEffect(() => {
    if (channelId !== null) localStorage.setItem("channelId", String(channelId))
  }, [channelId])

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-2xl font-semibold tracking-tight">
          YouTube Summarizer
        </h1>
        <ChannelSelect
          channels={channels ?? []}
          value={channelId}
          onChange={setChannelId}
        />
        <Button variant="outline" onClick={() => setPromptsOpen(true)}>
          Manage prompts
        </Button>
        <Button variant="outline" onClick={() => setManageOpen(true)}>
          Manage channels
        </Button>
        <Button variant="outline" onClick={() => setSettingsOpen(true)}>
          Settings
        </Button>
        <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-1">
          <MonitorStatus />
          <PriceNotice onOpenSettings={() => setSettingsOpen(true)} />
        </div>
      </header>

      {channels && channels.length === 0 && (
        <p className="text-muted-foreground py-16 text-center">
          No channels yet — add a prompt in “Manage prompts”, then a channel in
          “Manage channels”.
        </p>
      )}

      {channelId !== null && (
        <Tabs defaultValue="process">
          <TabsList className="mb-4">
            <TabsTrigger value="process">Process videos</TabsTrigger>
            <TabsTrigger value="summaries">Summaries</TabsTrigger>
            <TabsTrigger value="mentions">Mentions</TabsTrigger>
            <TabsTrigger value="search">Search</TabsTrigger>
            <TabsTrigger value="ask">Ask</TabsTrigger>
          </TabsList>
          <TabsContent value="process">
            <ProcessTab key={channelId} channelId={channelId} />
          </TabsContent>
          <TabsContent value="summaries">
            <SummaryList channelId={channelId} />
          </TabsContent>
          <TabsContent value="mentions">
            <MentionsTab key={channelId} channelId={channelId} />
          </TabsContent>
          <TabsContent value="search">
            <SearchTab key={channelId} channelId={channelId} />
          </TabsContent>
          <TabsContent value="ask">
            <AskTab key={channelId} channelId={channelId} />
          </TabsContent>
        </Tabs>
      )}

      <ChannelManagerDialog open={manageOpen} onOpenChange={setManageOpen} />
      <PromptManagerDialog open={promptsOpen} onOpenChange={setPromptsOpen} />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  )
}

export default App

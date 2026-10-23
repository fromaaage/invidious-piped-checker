import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1050
    height: 720
    visible: true
    title: "Invidious & Piped Checker"

    property bool hideDead: true

    function statusColor(s) {
        return s === "fav" ? "#2e9d5b" : s === "online" ? "#d49a1a" : s === "bad" ? "#c0453b"
             : s === "dead" ? "#777777" : palette.mid
    }
    function appColor(a) {
        return a === "Piped" ? "#4a8fe0" : a === "Invidious" ? "#b06ad8" : a === "Poke" ? "#e0609a"
             : a === "CloudTube" ? "#3aa8a0" : "#d98a3a"
    }

    // prefill a copied YouTube link when the window gets focus
    onActiveChanged: {
        if (active && linkField.text === "") {
            const link = backend.clipboardLink()
            if (link) linkField.text = link
        }
    }

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.margins: 6
            spacing: 10

            Button {
                text: "▶  Watch YouTube"
                highlighted: true
                enabled: backend.bestUrl !== ""
                onClicked: backend.open(backend.bestUrl)
                ToolTip.visible: hovered
                ToolTip.text: backend.bestUrl !== "" ? "Opens " + backend.bestUrl
                                                     : "No favorite yet – test an instance below"
            }
            Button {
                text: backend.busy ? "Checking …" : "Check again"
                enabled: !backend.busy
                onClicked: backend.scan()
            }
            ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, backend.total)
                value: backend.done
                indeterminate: backend.busy && backend.total === 0
            }
            Label {
                text: "<b>" + backend.favCount + "</b> working · " + backend.onlineCount + " to test · "
                      + backend.deadCount + " dead"
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        // open a YouTube link on the best favorite
        RowLayout {
            Layout.fillWidth: true
            TextField {
                id: linkField
                Layout.fillWidth: true
                placeholderText: "Paste a YouTube link (video, channel, playlist, search) …"
                onAccepted: openBtn.clicked()
            }
            Button {
                id: openBtn
                text: "Open on favorite"
                enabled: backend.bestUrl !== "" && linkField.text.length > 0
                onClicked: { backend.openLink(linkField.text); linkField.clear() }
            }
        }

        TabBar {
            id: tabs
            objectName: "tabs"
            Layout.fillWidth: true
            TabButton { text: "Instances" }
            TabButton { text: "Subscriptions (" + backend.subsCount + ")" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            // ===================== Instances =====================
            ColumnLayout {
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Frame {
                        Layout.fillWidth: true
                        visible: !backend.busy && backend.total > 0 && backend.favCount === 0
                        background: Rectangle { color: "#30d49a1a"; radius: 6 }
                        Label {
                            anchors.fill: parent
                            wrapMode: Text.WordWrap
                            text: backend.onlineCount > 0
                                  ? "How it works: click “Test” on a yellow instance. If the video plays in your browser, click “Works” – it becomes a favorite and opens with “Watch YouTube”."
                                  : "No public instance is online right now. Check again later or add your own below."
                        }
                    }
                    Item { Layout.fillWidth: true; visible: !(backend.total > 0 && backend.favCount === 0 && !backend.busy) }
                    Switch {
                        text: "Hide dead"
                        checked: win.hideDead
                        onToggled: win.hideDead = checked
                    }
                }

                ListView {
                    id: list
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: backend.model
                    spacing: 2
                    ScrollBar.vertical: ScrollBar {}

                    delegate: Rectangle {
                        id: row
                        required property string app
                        required property string url
                        required property string webUrl
                        required property string flag
                        required property string latency
                        required property string status
                        required property string note
                        required property string sources
                        required property string uptime

                        width: list.width
                        height: visible ? 48 : 0
                        visible: !(win.hideDead && status === "dead")
                        radius: 4
                        color: status === "fav" ? "#152e9d5b" : hover.hovered ? palette.alternateBase : "transparent"
                        HoverHandler { id: hover }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 6
                            spacing: 10

                            Rectangle {
                                width: 12; height: 12; radius: 6
                                color: win.statusColor(row.status)
                                BusyIndicator {
                                    anchors.centerIn: parent
                                    width: 22; height: 22
                                    running: row.status === "pending" && backend.busy
                                    visible: running
                                }
                            }
                            Label {
                                text: row.app
                                Layout.preferredWidth: 80
                                color: win.appColor(row.app)
                                font.bold: true
                            }
                            Label { text: row.flag; font.pixelSize: 18 }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Label {
                                    text: row.webUrl || row.url
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                    font.bold: row.status === "fav"
                                }
                                Label {
                                    text: row.note + (row.uptime ? " · " + row.uptime : "")
                                    font.pixelSize: 11
                                    opacity: 0.7
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                    ToolTip.visible: noteHover.hovered
                                    ToolTip.text: "Source: " + row.sources
                                    HoverHandler { id: noteHover }
                                }
                            }
                            Label {
                                text: row.latency
                                Layout.preferredWidth: 56
                                horizontalAlignment: Text.AlignRight
                                opacity: 0.7
                            }

                            // actions depending on status
                            Button {
                                text: "Open"
                                visible: row.status === "fav"
                                onClicked: backend.open(row.webUrl)
                            }
                            Button {
                                text: "Test"
                                visible: row.status === "online" || row.status === "bad"
                                onClicked: backend.openTest(row.webUrl)
                                ToolTip.visible: hovered
                                ToolTip.text: "Opens a 19-second test video in your browser"
                            }
                            Button {
                                text: "✓ Works"
                                visible: row.status === "online" || row.status === "bad"
                                onClicked: backend.mark(row.webUrl, true)
                            }
                            Button {
                                text: "✗ Broken"
                                visible: row.status === "online"
                                onClicked: backend.mark(row.webUrl, false)
                            }
                            ToolButton {
                                text: "↶"
                                visible: row.status === "fav" || row.status === "bad"
                                onClicked: backend.unmark(row.webUrl)
                                ToolTip.visible: hovered
                                ToolTip.text: "Clear mark"
                            }
                            ToolButton {
                                text: "⧉"
                                onClicked: backend.copy(row.webUrl || row.url)
                                ToolTip.visible: hovered
                                ToolTip.text: "Copy URL"
                            }
                        }
                    }
                }

                // custom instance
                RowLayout {
                    Layout.fillWidth: true
                    ComboBox {
                        id: appBox
                        model: ["Invidious", "Piped", "Poke", "CloudTube", "Hyperpipe"]
                    }
                    TextField {
                        id: urlField
                        Layout.fillWidth: true
                        placeholderText: "Add an instance, e.g. https://invidious.example.org"
                        onAccepted: addBtn.clicked()
                    }
                    Button {
                        id: addBtn
                        text: "Add"
                        enabled: urlField.text.length > 8
                        onClicked: { backend.addInstance(appBox.currentText, urlField.text); urlField.clear() }
                    }
                }
            }

            // ===================== Subscriptions =====================
            ColumnLayout {
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    TextField {
                        id: channelField
                        Layout.fillWidth: true
                        placeholderText: "Add a channel: YouTube channel link or @handle"
                        onAccepted: subBtn.clicked()
                    }
                    Button {
                        id: subBtn
                        text: "Subscribe"
                        enabled: channelField.text.length > 1
                        onClicked: { backend.addChannel(channelField.text); channelField.clear() }
                    }
                    Button {
                        text: "Import …"
                        onClicked: importDialog.open()
                        ToolTip.visible: hovered
                        ToolTip.text: "Invidious JSON, OPML, YouTube Takeout CSV, NewPipe or FreeTube"
                    }
                    Button {
                        text: "Export …"
                        enabled: backend.subsCount > 0
                        onClicked: exportMenu.open()
                        Menu {
                            id: exportMenu
                            y: parent.height
                            MenuItem { text: "Invidious JSON"; onTriggered: { exportDialog.fmt = "json"; exportDialog.open() } }
                            MenuItem { text: "OPML (FreeTube, NewPipe, RSS)"; onTriggered: { exportDialog.fmt = "opml"; exportDialog.open() } }
                        }
                    }
                    Button {
                        text: "Import page on favorite"
                        enabled: backend.bestUrl !== ""
                        onClicked: backend.openImportPage()
                        ToolTip.visible: hovered
                        ToolTip.text: "Opens the Invidious import page – upload the exported JSON there to restore your account"
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: backend.subsCount === 0
                    wrapMode: Text.WordWrap
                    opacity: 0.8
                    text: "Your subscriptions are stored on this computer, not on an instance – they survive when an instance dies. Add channels above or import an export from YouTube, Invidious, NewPipe or FreeTube. New videos come from YouTube's public RSS feeds and open on your favorite instance."
                }

                SplitView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: backend.subsCount > 0

                    // channels
                    ListView {
                        id: channels
                        SplitView.preferredWidth: 280
                        clip: true
                        model: backend.subsModel
                        ScrollBar.vertical: ScrollBar {}
                        delegate: ItemDelegate {
                            required property string ucid
                            required property string name
                            width: channels.width
                            text: name
                            onClicked: backend.openChannel(ucid)
                            ToolButton {
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                text: "✕"
                                onClicked: backend.removeChannel(parent.ucid)
                                ToolTip.visible: hovered
                                ToolTip.text: "Unsubscribe"
                            }
                        }
                    }

                    // feed
                    ColumnLayout {
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Latest videos"; font.bold: true; Layout.fillWidth: true }
                            BusyIndicator { running: backend.feedBusy; visible: running; implicitHeight: 24; implicitWidth: 24 }
                            Button {
                                text: "Refresh"
                                enabled: !backend.feedBusy
                                onClicked: backend.refreshFeed()
                            }
                        }
                        ListView {
                            id: feed
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: backend.feedModel
                            ScrollBar.vertical: ScrollBar {}
                            delegate: ItemDelegate {
                                required property string id
                                required property string title
                                required property string channel
                                required property string age
                                width: feed.width
                                onClicked: backend.openVideo(id)
                                contentItem: RowLayout {
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        Label { text: title; elide: Text.ElideRight; Layout.fillWidth: true }
                                        Label { text: channel; font.pixelSize: 11; opacity: 0.65 }
                                    }
                                    Label { text: age; opacity: 0.65 }
                                }
                            }
                        }
                    }
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            TextArea {
                id: log
                readOnly: true
                font.family: "monospace"
                font.pixelSize: 11
                Connections {
                    target: backend
                    function onLogLine(line) { log.append(line) }
                }
            }
        }
    }

    FileDialog {
        id: importDialog
        title: "Import subscriptions"
        nameFilters: ["Subscription exports (*.json *.opml *.xml *.csv *.db)", "All files (*)"]
        onAccepted: backend.importSubs(selectedFile)
    }
    FileDialog {
        id: exportDialog
        property string fmt: "json"
        title: "Export subscriptions"
        fileMode: FileDialog.SaveFile
        currentFile: fmt === "opml" ? "subscriptions.opml" : "subscriptions.json"
        onAccepted: backend.exportSubs(selectedFile, fmt)
    }
}

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1000
    height: 700
    visible: true
    title: "Invidious & Piped Checker"

    property bool hideDead: true

    function statusColor(s) {
        return s === "fav" ? "#2e9d5b" : s === "online" ? "#d49a1a" : s === "bad" ? "#c0453b"
             : s === "dead" ? "#777777" : palette.mid
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
                icon.name: "view-refresh"
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
            Switch {
                text: "Hide dead"
                checked: win.hideDead
                onToggled: win.hideDead = checked
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

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
                        Layout.preferredWidth: 72
                        color: row.app === "Piped" ? "#4a8fe0" : "#b06ad8"
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
                            text: row.note
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
                model: ["Invidious", "Piped"]
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

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: 70
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

}

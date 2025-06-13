# 🐍 Python Material Node Collector 🐍

This Python script, designed for Houdini, traverses a node graph to find **Material SOP Nodes**, collects their group parameters, and builds a concatenated expression. It sets this expression on the `group` parameter of the current node.

The intended use is to have this code inside a blast or color node, and by the push of the button 
<br>```exec(hou.pwd().parm('code').eval())```
<br>Execute the main code and color or delete any already assigned material


---

## 📝 **Features**
- **🔍 Recursive Search:** Finds all Material SOP nodes connected to the input network up to a specified depth.
- **⚙️ Dynamic Expression Building:** Collects group parameters and constructs an expression linking them.
- **💡 Debugging Support:** Prints detailed information about visited nodes and found parameters. Because i am a dumbass and it took a long time to actually work.

---

## 📋 **Script Workflow**
1. **🌐 Collect Material Nodes:** 
   - Recursively traverse the node graph starting from the current node (`hou.pwd()`).
   - Identify and store Material SOP nodes.
2. **📦 Extract Group Parameters:**
   - For each Material SOP node, extract `group` parameters (`group1`, `group2`, ... up to `group50`).
3. **🧩 Build Expressions:**
   - Concatenate these parameters into a single expression string.
   - Set the expression in the `group` parameter of the current node, if it exists.

---

## 🌟 **Key Highlights**
- **🌌 Max Depth Control:** Prevent infinite recursion by setting `max_depth`.
- **🚀 Automation Ready:** Automates tedious tasks for complex node graphs.
- **💡 Debug-Friendly:** Helps troubleshoot by printing intermediate results.

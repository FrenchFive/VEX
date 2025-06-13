def collect_material_nodes(node, max_depth=50):
    visited = set()
    queue = [(node, 0)]
    material_nodes = []
    while queue:
        current_node, depth = queue.pop(0)
        if depth > max_depth or current_node in visited:
            continue
        visited.add(current_node)
        # Print the node path and type for debugging
        print("Visiting node:", current_node.path(), "Type:", current_node.type().name())
        # Check if the node is a Material SOP node
        if current_node.type().category().name() == 'Sop' and current_node.type().name() == 'material':
            material_nodes.append(current_node)
        # Traverse inputs recursively
        for input_node in current_node.inputs():
            if input_node is not None:
                queue.append((input_node, depth + 1))
    print("Material nodes found:", material_nodes)
    return material_nodes

print("HELLO WORLD")
material_nodes = collect_material_nodes(hou.pwd())
expressions = []
for node in material_nodes:
    for i in range(1, 51):
        parm = node.parm("group{}".format(i))
        if parm and parm.eval():
            print("Found parameter:", parm.path(), "with value:", parm.eval())
            # Use absolute path
            parm_path = "{}/group{}".format(node.path(), i)
            print("Parameter path:", parm_path)
            # Build the expression without backticks
            expr = 'chs("{}")'.format(parm_path)
            print("Expression:", expr)
            expressions.append(expr)
# Build the final expression by concatenating with " + ' ' + "
if expressions:
    expression_string = ' + " " + '.join(expressions)
    group_parm = hou.pwd().parm("group")
    if group_parm:
        group_parm.setExpression(expression_string, language=hou.exprLanguage.Hscript)
        print("Group parameter set to:", group_parm.eval())
    else:
        print("The 'group' parameter does not exist on the current node.")
else:
    print("No expressions to set for the 'group' parameter.")
